from typing import List
from dataclasses import dataclass, field
import json

from transformers import AutoConfig, AutoTokenizer, DataCollatorWithPadding
from datasets import Dataset

from primeqa.pipelines.components.base import ReaderComponent
from primeqa.mrc.models.heads.extractive import EXTRACTIVE_HEAD
from primeqa.mrc.models.task_model import ModelForDownstreamTasks
from primeqa.mrc.processors.preprocessors.base import BasePreProcessor
from primeqa.mrc.processors.postprocessors.extractive import ExtractivePostProcessor
from primeqa.mrc.processors.postprocessors.scorers import SupportedSpanScorers
from primeqa.mrc.trainers.mrc import MRCTrainer
from primeqa.pipelines.components.reader.text_classifier_reader import TextClassifierReader
from primeqa.pipelines.components.reader.extractive import ExtractiveReader


@dataclass
class ExtractiveWithBooleanReader(ReaderComponent):
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

    boolean_config: str = field(
        default="tydi_boolqa_config.json",
        metadata={"name": "Model", "api_support": True},
    )
    model: str = field(
        default="PrimeQA/nq_tydi_sq1-reader-xlmr_large-20221110",
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
        print('in __post_init__')
        # Placeholder variables
        self._loaded_model = None
        self._tokenizer = None
        self._preprocessor = None
        self._scorer_type_as_enum = None
        self._data_collector = None

        self._extractiveReader = ExtractiveReader()
        self._booleanQTCReader = TextClassifierReader()
        self._booleanEVCReader = TextClassifierReader()
        self._extractiveReader.__post_init__()
        self._booleanQTCReader.__post_init__()
        self._booleanEVCReader.__post_init__()



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
        # TODO this is restricted to file system
        boolean_config=json.load(open(self.boolean_config))
        qtc_config=boolean_config['qtc']
        evc_config=boolean_config['evc']
        # TODO this in config file?
        mrc_config_dict={ k:getattr(self,k) for k in self.__class__.__dataclass_fields__.keys() }

        self._extractiveReader.load(args, **mrc_config_dict)
        self._booleanQTCReader.load(args, **qtc_config)
        self._booleanEVCReader.load(args, **evc_config)

    def apply(self, input_texts: List[str], context: List[List[str]], *args, **kwargs):
        extractive_predictions=self._extractiveReader.apply(input_texts, context, args, kwargs)
        qtc_prediction_output=self._booleanQTCReader._predict(input_texts, context, args, kwargs)
        evc_prediction_output=self._booleanEVCReader._predict(input_texts, context, args, kwargs)

        qtc_pred_key=self._booleanQTCReader.output_label_prefix+"_pred"
        evc_pred_key=self._booleanEVCReader.output_label_prefix+"_pred"


        for extractive_prediction in extractive_predictions:
            xp=extractive_prediction[0]
            qtcp = qtc_prediction_output.predictions[xp['example_id']][0][qtc_pred_key]
            evcp = evc_prediction_output.predictions[xp['example_id']][0][evc_pred_key]
            mrcp = xp['span_answer_text']
            xp['span_answer_text'] = f'question type: {qtcp} boolean answer: {evcp} mrc: {mrcp}'


        return extractive_predictions
