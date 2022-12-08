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
from primeqa.pipelines.components.reader.boolean_qtc import BooleanQTCReader
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

    #model: str = field(
    #    default="PrimeQA/nq_tydi_sq1-reader-xlmr_large-20221110",
    #    metadata={"name": "Model", "api_support": True},
    #)
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
        self._extractiveReader = ExtractiveReader()
        self._booleanQTCReader = BooleanQTCReader()
        self._extractiveReader.__post_init__()
        self._booleanQTCReader.__post_init__()

        self._extractiveReader.min_score_threshold = self.min_score_threshold
        self._extractiveReader.scorer_type = self.scorer_type
        self._extractiveReader.max_answer_length = self.max_answer_length
        self._extractiveReader.max_num_answers = self.max_num_answers
        self._extractiveReader.n_best_size = self.n_best_size
        self._extractiveReader.max_seq_len = self.max_seq_len
        self._extractiveReader.stride = self.stride
        self._extractiveReader.use_fast = self.use_fast

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
        self._extractiveReader.load(args, kwargs)
        self._booleanQTCReader.load(args, kwargs)

    def apply(self, input_texts: List[str], context: List[List[str]], *args, **kwargs):
        extractive_predictions=self._extractiveReader.apply(input_texts, context, args, kwargs)
        qtc_predictions=self._booleanQTCReader.apply(input_texts, context, args, kwargs)

        # since qtc_predictions is generally top1 and 
        # extractive_predictions is generally topn
        # this only applies the question type text to the top prediction ...
        for xps, qtcps in zip(extractive_predictions, qtc_predictions):
            for xp, qtcp in zip(xps, qtcps):
                xp['span_answer_text'] = (
                    'The question type is ' +
                    qtcp['span_answer_text'] + 
                    ' . ' +
                    xp['span_answer_text']
                )

        return extractive_predictions