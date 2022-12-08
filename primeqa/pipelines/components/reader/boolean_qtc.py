from typing import List
from dataclasses import dataclass, field
import json
import numpy as np

from transformers import (
    AutoConfig, 
    AutoTokenizer, 
    DataCollatorWithPadding, 
    AutoModelForSequenceClassification
)
from datasets import Dataset
from primeqa.boolqa.processors.postprocessors.boolqa_classifier import BoolQAClassifierPostProcessor
from primeqa.text_classification.processors.postprocessors.extractive import ExtractivePipelinePostProcessor
from primeqa.boolqa.processors.preprocessors.boolqa_classifier import BoolQAClassifierPreProcessor
from primeqa.boolqa.trainers.adapterPrimeTrainer import InstrumentedTrainer

from primeqa.pipelines.components.base import ReaderComponent
from primeqa.mrc.models.heads.extractive import EXTRACTIVE_HEAD
from primeqa.mrc.models.task_model import ModelForDownstreamTasks
from primeqa.mrc.processors.preprocessors.base import BasePreProcessor
from primeqa.mrc.processors.postprocessors.extractive import ExtractivePostProcessor
from primeqa.mrc.processors.postprocessors.scorers import SupportedSpanScorers
from primeqa.mrc.trainers.mrc import MRCTrainer
from primeqa.text_classification.processors.postprocessors.text_classifier import TextClassifierPostProcessor
from primeqa.text_classification.processors.preprocessors.text_classifier import TextClassifierPreProcessor
from primeqa.text_classification.trainers.nway import NWayTrainer


@dataclass
class BooleanQTCReader(ReaderComponent):
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

    model: str = field(
        default="PrimeQA/tydi-tydi_boolean_question_classifier-xlmr_large-20221117",
        metadata={"name": "Model", "api_support": True},
    )
    use_fast: bool = field(
        default=True,
        metadata={
            "name": "Use the fast version of the tokenizer",
            "options": [True, False],
        },
    )
    stride: int = field(
        default=128,
        metadata={
            "name": "Stride",
            "description": "Step size to move sliding window across context",
            "range": [8, 256, 8],
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
    scorer_type: str = field(
        default=SupportedSpanScorers.WEIGHTED_SUM_TARGET_TYPE_AND_SCORE_DIFF.value,
        metadata={
            "name": "Scoring algorithm",
            "options": [
                SupportedSpanScorers.SCORE_DIFF_BASED.value,
                SupportedSpanScorers.TARGET_TYPE_WEIGHTED_SCORE_DIFF.value,
                SupportedSpanScorers.WEIGHTED_SUM_TARGET_TYPE_AND_SCORE_DIFF.value,
            ],
        },
    )
    min_score_threshold: float = field(
        default=None,
        metadata={
            "name": "Minimum score threshold",
            "api_support": True,
            "exclude_from_hash": True,
        },
    )

    def __post_init__(self):
        # Placeholder variables
        self._loaded_model = None
        self._tokenizer = None
        self._preprocessor = None
        self._scorer_type_as_enum = None
        self._data_collector = None

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
        task_heads = EXTRACTIVE_HEAD
        # Load configuration for model
        config = AutoConfig.from_pretrained(self.model)

        # Initialize tokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model,
            use_fast=self.use_fast,
            config=config,
        )
    

        config.sep_token_id = self._tokenizer.convert_tokens_to_ids(
            self._tokenizer.sep_token
        )

        self._loaded_model = AutoModelForSequenceClassification.from_pretrained(self.model)        


        # Initialize preprocessor
        #self._preprocessor = BasePreProcessor(
        #    stride=self.stride,
        #    max_seq_len=self.max_seq_len,
        #    tokenizer=self._tokenizer,
        #)
        # self._preprocessor = BoolQAClassifierPreProcessor(
        #     sentence1_key='question',#qtc_config['sentence1_key'],
        #     sentence2_key=None,#qtc_config['sentence2_key'],
        #     tokenizer=self._tokenizer,
        #     load_from_cache_file=False,
        #     max_seq_len=self._tokenizer.model_max_length,
        #     #label_list=qtc_config['label_list'],
        #     #id_key=qtc_config['id_key'],
        #     padding=False
        # )   
        self._preprocessor = TextClassifierPreProcessor(
            sentence1_key='question',#qtc_config['sentence1_key'],
            sentence2_key=None,#qtc_config['sentence2_key'],
            language_key=None,
            tokenizer=self._tokenizer,
            load_from_cache_file=False,
            max_seq_len=self._tokenizer.model_max_length,
            example_id_key='example_id',
            label_list=['boolean', 'short_answer'],
            #label_list=qtc_config['label_list'],
            #id_key=qtc_config['id_key'],
            padding=False
        )                   

        # Configure scorer
        if self.scorer_type == SupportedSpanScorers.SCORE_DIFF_BASED.value:
            self._scorer_type_as_enum = SupportedSpanScorers.SCORE_DIFF_BASED
        elif (
            self.scorer_type
            == SupportedSpanScorers.TARGET_TYPE_WEIGHTED_SCORE_DIFF.value
        ):
            self._scorer_type_as_enum = (
                SupportedSpanScorers.TARGET_TYPE_WEIGHTED_SCORE_DIFF
            )
        elif (
            self.scorer_type
            == SupportedSpanScorers.WEIGHTED_SUM_TARGET_TYPE_AND_SCORE_DIFF.value
        ):
            self._scorer_type_as_enum = (
                SupportedSpanScorers.WEIGHTED_SUM_TARGET_TYPE_AND_SCORE_DIFF
            )
        else:
            raise ValueError(f"Unsupported scorer type: {self.scorer_type}")

        # Configure data collector
        self._data_collector = DataCollatorWithPadding(self._tokenizer)

    def apply(self, input_texts: List[str], context: List[List[str]], *args, **kwargs):
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

        min_score_threshold = (
            kwargs["min_score_threshold"]
            if "min_score_threshold" in kwargs
            else self.min_score_threshold
        )

        # Step 2: Initialize post processor
#        postprocessor = ExtractivePostProcessor(
#            k=max_num_answers,
#            n_best_size=self.n_best_size,
#            max_answer_length=max_answer_length,
#            scorer_type=self._scorer_type_as_enum,
#            single_context_multiple_passages=self._preprocessor._single_context_multiple_passages,
#        )


        postprocessor = TextClassifierPostProcessor(
            k=max_num_answers, 
            drop_label=None,
            n_best_size=self.n_best_size,
            max_answer_length=max_answer_length,
            #sentence1_key='question',#qtc_config['sentence1_key'],
            label_list = ['boolean', 'short_answer'],#qtc_config['label_list'],
            id_key='example_id', #qtc_config['id_key'],
            output_label_prefix='qtc',#qtc_config['output_label_prefix'],
        )        

        # Step 3: Load trainer
#        trainer = MRCTrainer(
#            model=self._loaded_model,
#            tokenizer=self._tokenizer,
#            data_collator=self._data_collector,
#            post_process_function=postprocessor.process,
#        )

        trainer = NWayTrainer( 
            model=self._loaded_model,
            tokenizer=self._tokenizer,
            data_collator=self._data_collector,
            post_process_function=postprocessor.process,
#            args=training_args
        )        

        # Step 4: Prepare dataset from input texts and contexts
        eval_examples = Dataset.from_dict(
            dict(
                question=input_texts,
                context=context,
                example_id=[str(idx) for idx in range(len(input_texts))],
            )
        )

        eval_examples, eval_dataset = self._preprocessor.process_eval(eval_examples)

        # Step 5: Run predict
        predictions = [[] for _ in range(len(input_texts))]
        prediction_output=trainer.predict(eval_dataset, eval_examples)


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