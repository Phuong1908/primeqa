import logging
from typing import List
from dataclasses import dataclass, field
import json
import numpy as np
import pandas as pd
import torch

from transformers import (
    AutoConfig, 
    AdapterConfig,
    AutoTokenizer, 
    DataCollatorWithPadding, 
    AutoModelForSequenceClassification
)
from datasets import Dataset

from primeqa.pipelines.components.base import ReaderComponent
from primeqa.mrc.models.heads.extractive import EXTRACTIVE_HEAD
from primeqa.mrc.processors.postprocessors.scorers import SupportedSpanScorers
from primeqa.text_classification.processors.postprocessors.text_classifier import TextClassifierPostProcessor
from primeqa.text_classification.processors.preprocessors.text_classifier import TextClassifierPreProcessor
from primeqa.text_classification.trainers.nway import NWayTrainer


@dataclass
class AdapterTextClassifierReader(ReaderComponent):
    # TODO update summary
    """_summary_

    Args:
        model (str, optional): Model. Defaults to "PrimeQA/nq_tydi_sq1-reader-xlmr_large-20221110".
        use_fast (bool, optional): If set to "True", uses the fast version of the tokenizer. Defaults to True.
        stride (int, optional): Step size to move sliding window across context. Defaults to 128.
        max_seq_len (int, optional): Maximum length of question and context inputs to the model (in word pieces/bpes). Defaults to 512.
        n_best_size (int, optional): Maximum number of start/end logits to consider (max values). Defaults to 20.
        max_num_answers (int, optional): Maximum number of answers. Defaults to 5.
        max_answer_length (int, optional): Maximum answer length. Defaults to 32.
        scorer_type (str, optional): Scoring algorithm. Defaults to "weighted_sum_target_type_and_score_diff".
        min_score_threshold: (float, optional): Minimum score threshold. Defaults to None.

    Important:
        1. Each field has metadata property which can carry additional information for other downstream usages.
        2. Two special keys (api_support and exclude_from_hash) are defined in "metadata" property.
            a. api_support (bool, optional): If set to True, that parameter is exposed via service layer. Defaults to False.
            b. exclude_from_hash (bool,optional): If set to True, that parameter is not considered while building the hash representation for the object. Defaults to False.


    Returns:
        _type_: _description_
    """

    adapter_model: str = field(
        #default='PrimeQA/tydi-tydi_boolean_question_classifier-xlmr_large-20221117',
        default='foo',
        metadata={"name": "Model", "api_support": True},
    )
    use_fast: bool = field(
        default=True,
        metadata={
            "name": "Use the fast version of the tokenizer",
            "options": [True, False],
        },
    )
    max_seq_len: int = field(
        default=512,
        metadata={
            "name": "Maximum sequence length",
            "description": "Maximum length of question and context inputs to the model (in word pieces/bpes)",
            "range": [32, 512, 8],
        },
    )
    n_best_size: int = field(
        default=20,
        metadata={
            "name": "N",
            "description": "Maximum number of start/end logits to consider (max values)",
            "range": [1, 50, 1],
        },
    )
    max_num_answers: int = field(
        default=3,
        metadata={
            "name": "Maximum number of answers",
            "range": [1, 5, 1],
            "api_support": True,
            "exclude_from_hash": True,
        },
    )
    max_answer_length: int = field(
        default=1000,
        metadata={
            "name": "Maximum answer length",
            "range": [2, 2000, 2],
            "api_support": True,
            "exclude_from_hash": True,
        },
    )
    id_key: str = field(
        default='example_id',
        metadata={
            "name": "unique identifier for examples",
            "api_support": False,
            "exclude_from_hash": True,                
        }
    )
    output_label_prefix: str = field(
        default='qtc',
        metadata={
            "name": "prefix for output labels",
            "api_support": False,
            "exclude_from_hash": False,       
        }
    )    
    sentence1_key: str = field(
        default='question',
        metadata={
            "name": "sentence1 key for preprocessor",
            "api_support": False,
            "exclude_from_hash": True,            
        },
    )
    sentence2_key: str = field(
        default=None,
        metadata={
            "name": "sentence2 key for preprocessor",
            "api_support": False,
            "exclude_from_hash": True,            
        },
    )

    label_list_str: str = field(
        default='True False',
        metadata={
            "name": "mapping of numeric predictions to labels (for postprocessor)",
            "api_support": True,
            "exclude_from_hash": False,
        },        
    )

    def __post_init__(self):
        # Placeholder variables
        self._logger=None # initialized in load()
        self._loaded_model = None
        self._tokenizer = None
        self._preprocessor = None
        self._data_collector = None
        self.label_list = self.label_list_str.split(' ')

    def __hash__(self) -> int:
        # Step 1: Identify all fields to be included in the hash
        hashable_fields = [
            k
            for k, v in self.__class__.__dataclass_fields__.items()
            if not "exclude_from_hash" in v.metadata
            or not v.metadata["exclude_from_hash"]
        ]

        # Step 2: Run
        return hash(
            f"{self.__class__.__name__}::{json.dumps({k: v for k, v in vars(self).items() if k in hashable_fields }, sort_keys=True)}"
        )

    def load(self, *args, **kwargs):
        # TODO should the keys in this file match the other one? model vs model_name_or_path
        for k in ['id_key', 'sentence1_key', 'sentence2_key', 'label_list', 'output_label_prefix', 'adapter_model', '_tokenizer', '_loaded_model']:
            if k in kwargs:
                setattr(self, k, kwargs[k])

        if self._logger is None:
            self._logger = logging.getLogger(self.__class__.__name__ +'-'+'-'.join(self.label_list))
            self._logger.setLevel(logging.INFO)
            self._logger.info("%s is successfully loaded.", self.__class__.__name__)

        # TODO this is ugly
        if self.output_label_prefix=='question_type':
            self._head_key='qtc_head'
            self._adapter_key='qtc'
        elif self.output_label_prefix=='boolean_answer':
            self._head_key='evc_head'
            self._adapter_key='evc'

        # Load configuration for model
        # config = AutoConfig.from_pretrained(self.model)

        # Initialize tokenizer
        # self._tokenizer = kwargs['tokenizer']
        # self._tokenizer = AutoTokenizer.from_pretrained(
        #     self.model,
        #     use_fast=self.use_fast,
        #     config=config,
        # )
    

        #config.sep_token_id = self._tokenizer.convert_tokens_to_ids(
        #    self._tokenizer.sep_token
        #)


        adapter_config = AdapterConfig.load(
            kwargs['adapter_model'] + '/adapter_config.json',
            non_linearity=None,  # non_linearity=adapter_args.adapter_non_linearity,
            reduction_factor=None  # reduction_factor=adapter_args.adapter_reduction_factor,
        )

        self._loaded_model.roberta.load_adapter(
            kwargs['adapter_model'],            
            config=adapter_config,
            load_as=self._adapter_key,
        )

        head_wts=torch.load(kwargs['adapter_model'] + '/pytorch_model_head.bin', map_location=torch.device('cpu'))

        # TODO this is ugly
        mapped_head_wts={
            'classifier.dense.weight': head_wts['task_heads.qa_head.classifier.dense.weight'],
            'classifier.dense.bias': head_wts['task_heads.qa_head.classifier.dense.bias'],
            'classifier.out_proj.weight': head_wts['task_heads.qa_head.classifier.out_proj.weight'],
            'classifier.out_proj.bias': head_wts['task_heads.qa_head.classifier.out_proj.bias']
        }
        if self._head_key=='qtc_head':
            self._loaded_model.task_heads.qtc_head.load_state_dict(mapped_head_wts)
        elif self._head_key=='evc_head':
            self._loaded_model.task_heads.evc_head.load_state_dict(mapped_head_wts)
         #  self._loaded_model = AutoModelForSequenceClassification.from_pretrained(self.model)        



        self._preprocessor = TextClassifierPreProcessor(
            sentence1_key=self.sentence1_key,
            sentence2_key=self.sentence2_key,
            language_key=None,
            tokenizer=self._tokenizer,
            load_from_cache_file=False,
            max_seq_len=self._tokenizer.model_max_length,
            example_id_key=self.id_key,
            label_list=self.label_list,
            padding=False
        )                   



        # Configure data collector
        self._data_collector = DataCollatorWithPadding(self._tokenizer)

    def _predict(self, input_texts: List[str], context: List[List[str]], *args, **kwargs):
        self._logger.info('input_texts: %s', str(input_texts))
        self._logger.info('context: %s', str(context))

        # Step 1: Locally update object variable values, if provided
        max_num_answers = (
            kwargs["max_num_answers"]
            if "max_num_answers" in kwargs
            else self.max_num_answers
        )

        max_answer_length = (
            kwargs["max_answer_length"]
            if "max_answer_length" in kwargs
            else self.max_answer_length
        )


        postprocessor = TextClassifierPostProcessor(
            k=max_num_answers, 
            drop_label=None,
            n_best_size=self.n_best_size,
            max_answer_length=max_answer_length,
            label_list = self.label_list,
            id_key=self.id_key,
            output_label_prefix=self.output_label_prefix,
        )        


        trainer = NWayTrainer( 
            model=self._loaded_model,
            tokenizer=self._tokenizer,
            data_collator=self._data_collector,
            post_process_function=postprocessor.process,
        )        

        # Step 4: Prepare dataset from input texts and contexts
        if self.sentence2_key is None:
            eval_examples = Dataset.from_dict(
                dict(
                    question=input_texts,
                    example_id=[str(idx) for idx in range(len(input_texts))],
                )
            )
        else:
            def generate_examples():
                for idx, input_text in enumerate(input_texts):
                    for ctx in context[idx]:
                        yield input_text, ctx, str(idx)

            df=pd.DataFrame.from_records( generate_examples(), 
                columns = [self.sentence1_key, self.sentence2_key, self.id_key] )
            eval_examples = Dataset.from_pandas(df)

        eval_examples, eval_dataset = self._preprocessor.process_eval(eval_examples)

        # Step 5: Run predict
        self._loaded_model.set_task_head(self._head_key)
        self._loaded_model.set_active_adapters([self._adapter_key])
        prediction_output=trainer.predict(eval_dataset, eval_examples)
        self._logger.info('prediction_output: %s', str(prediction_output))
        return prediction_output


    def apply(self, input_texts: List[str], context: List[List[str]], *args, **kwargs):
        prediction_output = self._predict(input_texts, context, args, kwargs)
        predictions = [[] for _ in range(len(input_texts))]

        for passage_idx, raw_predictions in prediction_output.predictions.items():
            for raw_prediction in raw_predictions:
                processed_prediction = {}
                processed_prediction["example_id"] = raw_prediction["example_id"]
                processed_prediction["span_answer_text"] = raw_prediction[
                    "qtc_pred"
                ]
                processed_prediction["span_answer"] = {'start_position':0, 'end_position':0}
                processed_prediction["confidence_score"] = np.float64(0.0)
                predictions[int(passage_idx)].append(processed_prediction)

        return predictions

@dataclass
class BooleanQTCReader(AdapterTextClassifierReader):
    model: str = field(
        default='PrimeQA/tydi-tydi_boolean_question_classifier-xlmr_large-20221117',
        metadata={"name": "Model", "api_support": True},
    )
    output_label_prefix: str = field(
        default='qtc',
        metadata={
            "name": "prefix for output labels",
            "api_support": False,
            "exclude_from_hash": False,       
        }
    )    
    sentence1_key: str = field(
        default='question',
        metadata={
            "name": "sentence1 key for preprocessor",
            "api_support": False,
            "exclude_from_hash": True,            
        },
    )
    sentence2_key: str = field(
        default=None,
        metadata={
            "name": "sentence2 key for preprocessor",
            "api_support": False,
            "exclude_from_hash": True,            
        },
    )
    label_list_str: str = field(
        default='factoid boolean',
        metadata={
            "name": "mapping of numeric predictions to labels (for postprocessor)",
            "api_support": True,
            "exclude_from_hash": False,            
        },        
    )    

    def __hash__(self) -> int:
        return super().__hash__()



@dataclass
class BooleanEVCReader(AdapterTextClassifierReader):
    model: str = field(
        default='PrimeQA/tydi-tydi_boolean_answer_classifier-xlmr_large-20221117',
        metadata={"name": "Model", "api_support": True},
    )
    output_label_prefix: str = field(
        default='evc',
        metadata={
            "name": "prefix for output labels",
            "api_support": False,
            "exclude_from_hash": False,       
        }
    )    
    sentence1_key: str = field(
        default='question',
        metadata={
            "name": "sentence1 key for preprocessor",
            "api_support": False,
            "exclude_from_hash": True,            
        },
    )
    sentence2_key: str = field(
        default='context',
        metadata={
            "name": "sentence2 key for preprocessor",
            "api_support": False,
            "exclude_from_hash": True,            
        },
    )
    label_list_str: str = field(
        default='no yes',
        metadata={
            "name": "mapping of numeric predictions to labels (for postprocessor)",
            "api_support": True,
            "exclude_from_hash": False,            
        },        
    )    

    def __hash__(self) -> int:
        return super().__hash__()

