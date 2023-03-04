
from colbert.infra.run import Run
from colbert.infra.config import ColBERTConfig, RunConfig
from colbert import Trainer

def distill_triples_with_retriever(given_triples, given_synth_queries, given_checkpoint, chosen_split, chosen_type, chosen_set, LoTTE_or_BEIR, chosen_BEIR_set, chosen_BEIR_type):
    
    with Run().context(RunConfig(nranks=4)):
        
        if LoTTE_or_BEIR == "LoTTE":
        	collection = '../ColBERT_FM/downloads/lotte/' + chosen_split + '/' + chosen_set +'/collection.tsv'
        elif LoTTE_or_BEIR == "BEIR":
        	collection = '../ColBERT_FM/beir_datasets/' + chosen_BEIR_set + '/' + chosen_BEIR_type +'/collection.tsv'

        config = ColBERTConfig(bsize=16, lr=1e-05, warmup=None, doc_maxlen=300, dim=128, nway=16, accumsteps=2, use_ib_negatives=False)
        trainer = Trainer(triples=given_triples, queries=given_synth_queries, collection=collection, config=config)

        distilled_checkpoint = trainer.train(checkpoint=given_checkpoint)

        print("Generated distilled checkpoint!")
        print(distilled_checkpoint)

        return distilled_checkpoint

