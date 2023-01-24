import json
from transformers import (
    HfArgumentParser,
    TrainingArguments,
)
from dataclasses import dataclass, field
from utils.model_utils.row_retriever_MITQA import RowRetriever
from utils.model_utils.reranker import re_rank_ae_output
from utils.link_predictor import predict_link_for_tables,train_link_generator
from utils.model_utils.table_retriever import train_table_retriever,predict_table_retriever
from utils.model_utils.process_row_retriever_output import preprocess_data_using_row_retrieval_scores,create_dataset_for_answer_extractor
from utils.model_utils.answer_extractor_multi_Answer import run_answer_extractor
from processors.preprocessors.preprocess_raw_data import preprocess_data
import logging
from typing import Any, Dict, List, Optional, Union
import torch
import os
import sys

@dataclass
class RRArguments():
   per_device_train_batch_size_rr: int = field(
       default=8, metadata={"help": "train batch size"}
    )
   per_device_eval_batch_size_rr: int = field(
       default=8, metadata={"help": "train batch size"}
    )
   rr_model_name: str = field(
       default='bert-base-uncased', metadata={"help": "Which model to use for RR training/testing"}
    )
   row_retriever_model_name_path: str = field(
       default='data/hybridqa/pretrained_models/rr.bin', metadata={"help": "Row retriever configuration file"}
    )
   pos_frac_per_epoch: List[float] = field(
      default_factory=lambda: [0.3, 0.3, 0.1, 0.0001, 0.0001], metadata={"help": "Positive fraction per epoch"}
   )
   group_frac_per_epoch: List[float]  = field(
      default_factory=lambda: [0.0, 0.5, 1.0, 1.0, 1.0], metadata={"help": "Positive fraction per epoch"}
   )
   num_train_epochs_rr: int = field(
      default=2,metadata={"help": "Number of epochs to train the row retriever"}
   )
   save_every_niter_rr: int = field(
      default=100,metadata={"help": "Save model after how many iterations"}
   )
   save_model_path_rr: str = field(
      default='data/hybridqa/models/rr.bin',metadata={"help": "Path to save row retrieval model"}
   )

@dataclass
class AEArguments(TrainingArguments):
   max_seq_length: int = field(
        default=512,metadata={"help": "Input Sequence Length"}
    )
   per_gpu_train_batch_size: int = field(
        default=8,metadata={"help": "Per GPU train batch size"}
    )
   train_batch_size: int = field(
        default=8,metadata={"help": "Per GPU train batch size"}
    )
   per_gpu_eval_batch_size: int = field(
        default=8,metadata={"help": "Per GPU train batch size"}
    )
   max_query_length: int = field(
        default=64,metadata={"help": "Maximum length of the query"}
    )
   threads: int = field(
        default=1,metadata={"help": "Number of preprocessing threads"}
    )
   null_score_diff_threshold: float = field(
        default=0.0,metadata={"help": "If null_score - best_non_null is greater than the threshold predict null"}
    )
   eval_batch_size: int = field(
        default=8,metadata={"help": "evaluation batch size"}
    )
   n_best_size: int = field(
        default=20,metadata={"help": "The total number of n-best predictions to generate in the nbest_predictions.json output file."}
    )
   do_lower_case: bool = field(
      default=True,metadata={"help": "do lowercase the input"}
   )
   do_train_ae: bool = field(
      default=False,metadata={"help": "do training"}
   )
   verbose_logging: bool = field(
      default=False,metadata={"help": "Log everything"}
   )
   do_predict_ae: bool = field(
      default=False,metadata={"help": "do predict"}
   )
   version_2_with_negative: bool = field(
      default=False,metadata={"help": "Squad 2.0"}
   )
   do_eval_ae: bool = field(
      default=False,metadata={"help": "do evaluation"}
   )
   device: torch.device = field(
        default=torch.device("cpu"),metadata={"help": "Whether to use cpu or gpu"}
    )
   n_gpu: int = field(
        default=1,metadata={"help": "Number of GPUs"}
    )
   max_answer_length: int = field(
        default=30,metadata={"help": "Maximum length of the query"}
    )
   model_name_or_path_ae: str = field(
      default="bert-base-uncased",metadata={"help":"model name or path"}
   )
   model_type: str = field(
       default='bert', metadata={"help": "Type of model to be train"}
    )
   config_name: str = field(
       default='', metadata={"help": "config name"}
    )
   tokenizer_name: str = field(
       default='', metadata={"help": "Tokenizer name"}
    )
   cache_dir: str = field(
       default='/tmp/', metadata={"help": "temp directory for caching"}
    )
   doc_stride: int = field(
       default=128, metadata={"help": "Doc Stride"}
    )
   train_file: str = field(
       default='data/hybridqa/ae_input_test.json', metadata={"help": "Type of model to be train"}
    )
   eval_file: str = field(
       default='data/hybridqa/ae_input_test.json', metadata={"help": "Type of model to be train"}
    )
   pred_ans_file: str = field(
      default='data/hybridqa/predictions/answer_extractor_output_test.json', metadata={"help": "Row retriever configuration file"}
   )
   
   
@dataclass
class LinkPredictorArguments:
   """
    Arguments pertaining to the link prediction module
   """
   model: str = field(
       default='gpt2', metadata={"help": "Pre-trained link prediction model"}
    )
   top_k: int = field(
       default=0, metadata={"help": "top k links to predict"}
    )
   top_p: float = field(
       default=0.9, metadata={"help": "top p value"}
    )
   seed_lg: int = field(
       default=42, metadata={"help": "random seed"}
    )
   dataset: str = field(
       default=None, metadata={"help": "which dataset to use"}
    )
   batch_size_lg: int = field(
       default=2, metadata={"help": "Batch size"}
    )
   linker_model: str = field(
       default=None, metadata={"help": "load from the checkpoint"}
    )
   every: int = field(
       default=50, metadata={"help": "Batch size"}
    )
   max_source_len: int = field(
       default=32, metadata={"help": "Maximum source length"}
    )
   max_target_len: int = field(
       default=16, metadata={"help": "Maximum target length"}
    )
   do_train_lg: bool = field(
        default=False, metadata={"help": "do_training"}
    )
   do_val_lg: bool = field(
        default=False, metadata={"help": "do validation"}
    )
   do_all_lg: bool = field(
        default=False, metadata={"help": "generate links for all the tables"}
    )
   learning_rate_lg: float = field(
       default=5e-6, metadata={"help": "learning rate for training"})
   shard: str = field(
       default=None, metadata={"help": "which shard"}
    )
   device_lg: torch.device = field(
        default=torch.device("cuda"),metadata={"help": "Whether to use cpu or gpu"}
    )
   
    
   

@dataclass
class HybridQAArguments:
    """
    Arguments pertaining to which model/config/tokenizer we are going to fine-tune from.
    """
    data_path_root: str = field(
       default='data/ottqa/', metadata={"help": "root path to store the preprocessed dataset"}
    )
    dataset_name: str = field(
       default='hybridqa', metadata={"help": "root path to store the preprocessed dataset"}
    )
    train_data_path: str = field(
       default='data/hybridqa/test.json', metadata={"help": "Train data path for training on user's own dataset"}
    )
    dev_data_path: str = field(
       default='data/hybridqa/toy.json', metadata={"help": "Dev data path for training on user's own dataset"}
    )
    test_data_path: str = field(
       default='data/hybridqa/test.json', metadata={"help": "Dev data path for training on user's own dataset"}
    )
    collections_file: str = field(
       default='linearized_tables.tsv', metadata={"help": "Dev data path for training on user's own dataset"}
    )
    
    test: Optional[bool] = field(
        default=False, metadata={"help": "Remove columns not required by the model when using an nlp.Dataset."}
    )
    test_data_path: str = field(
       default='data/hybridqa/test.json', metadata={"help": "Dev data path for training on user's own dataset"}
    )
    
    test: Optional[bool] = field(
        default=False, metadata={"help": "Remove columns not required by the model when using an nlp.Dataset."}
    )
    
    
    
    
    
def run_hybrid_qa():
   logger = logging.getLogger(__name__)
   logger.info("running hybridqa")
   hqa_parser = HfArgumentParser((HybridQAArguments,LinkPredictorArguments, RRArguments,AEArguments))

   if len(sys.argv) == 2 and sys.argv[1].endswith(".json"):
      hqa_args,lp_args,rr_args,ae_args,= hqa_parser.parse_json_file(json_file=os.path.abspath(sys.argv[1]))
   else:
      hqa_args,lp_args,rr_args,ae_args, = hqa_parser.parse_args_into_dataclasses()
   logger.info(hqa_args,lp_args,rr_args,ae_args)
   raw_train_data = json.load(open(hqa_args.train_data_path))
   raw_dev_data = json.load(open(hqa_args.dev_data_path))
   raw_test_data = json.load(open(hqa_args.test_data_path))
   test=False
   if hqa_args.test_data_path is not None and hqa_args.test:
      logger.info("Test Mode")
      test=True
      ae_args.do_predict_ae = True
      if hqa_args.dataset_name=="ottqa":
         retrieved_data = predict_table_retriever(hqa_args.data_path_root,hqa_args.collections_file,raw_dev_data)
         json.dump(retrieved_data,open(os.path.join(hqa_args.data_path_root,"table_retrieval_output_test.json"),"w"))
         linked_data = predict_link_for_tables(lp_args,retrieved_data)
         test_data_processed = preprocess_data(hqa_args.data_path_root,hqa_args.dataset_name,linked_data,split="test",test=test)
      else:
         test_data_processed = preprocess_data(hqa_args.data_path_root,hqa_args.dataset_name,raw_test_data,split="test",test=test)

      logger.info("Initial preprocessing done")
      rr = RowRetriever(hqa_args,rr_args)
      qid_scores_dict = rr.predict(test_data_processed)
      logger.info("Row retrieval predictions Done")
      test_processed_data = preprocess_data_using_row_retrieval_scores(raw_dev_data,qid_scores_dict,test)
      logger.info("Row retrieval output processed")
      answer_extraction_data = create_dataset_for_answer_extractor(test_processed_data,hqa_args.data_path_root,test)
      logger.info("Answer extraction data generated")
      ae_output_path,ae_output_path_nbest = run_answer_extractor(ae_args,answer_extraction_data)
      logger.info(ae_output_path)
      logger.info(ae_output_path_nbest)
      re_rank_ae_output(qid_scores_dict,ae_output_path_nbest,ae_args.pred_ans_file) 
   else:
      logger.info("Training Mode")
      if hqa_args.dataset_name == "ottqa":
         if hqa_args.train_tr:
            train_table_retriever(hqa_args.data_path_root,"triples_train.tsv")
         retrieved_data_train = predict_table_retriever(hqa_args.data_path_root,hqa_args.collections_file,raw_train_data)
         json.dump(retrieved_data_train,open(os.path.join(hqa_args.data_path_root,"table_retrieval_output_train.json"),"w"))
         if hqa_args.train_lp:
            train_link_generator(lp_args)
         linked_data_train = predict_link_for_tables(lp_args,retrieved_data_train)
         retrieved_data_dev = predict_table_retriever(hqa_args.data_path_root,hqa_args.collections_file,raw_dev_data)
         json.dump(retrieved_data_dev,open(os.path.join(hqa_args.data_path_root,"table_retrieval_output_dev.json"),"w"))
         linked_data_dev = predict_link_for_tables(lp_args,retrieved_data_dev)
         train_data_processed = preprocess_data(hqa_args.data_path_root,hqa_args.dataset_name,linked_data_train,split="train",test=test)
         dev_data_processed = preprocess_data(hqa_args.data_path_root,hqa_args.dataset_name,linked_data_dev,split="dev",test=test)
      else:
         train_data_processed = preprocess_data(hqa_args.data_path_root,hqa_args.dataset_name,raw_train_data,split="train",test=test)
         dev_data_processed = preprocess_data(hqa_args.data_path_root,hqa_args.dataset_name,raw_dev_data,split="dev",test=test)
      logger.info("Train: Initial preprocessing done")
      rr = RowRetriever(hqa_args,rr_args)
      logger.info("Train: Training row retrieval model")
      rr.train(train_data_processed,dev_data_processed)
      qid_scores_dict_train = rr.predict(train_data_processed)
      qid_scores_dict_dev = rr.predict(train_data_processed)
      train_processed_data = preprocess_data_using_row_retrieval_scores(raw_train_data,qid_scores_dict_train,test)
      dev_processed_data = preprocess_data_using_row_retrieval_scores(raw_dev_data,qid_scores_dict_dev,test)
      answer_extraction_train_data = create_dataset_for_answer_extractor(train_processed_data,hqa_args.data_path_root,test)
      answer_extraction_dev_data = create_dataset_for_answer_extractor(dev_processed_data,hqa_args.data_path_root,test)
      output_dir = run_answer_extractor(ae_args,answer_extraction_train_data)
      ae_args.do_train_ae = False
      ae_output_path,ae_output_path_nbest = run_answer_extractor(ae_args,answer_extraction_dev_data)
      re_rank_ae_output(qid_scores_dict_dev,ae_output_path_nbest,ae_args.pred_ans_file) 
      logger.info(f"Train: Training Done model saved at: {output_dir}")
      
      
      
      
      
if __name__ == '__main__':
    run_hybrid_qa()