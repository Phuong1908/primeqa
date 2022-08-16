# from colbert.indexing.codecs.residual import ResidualCodec
import primeqa.ir.dense.colbert_top.colbert.indexing.codecs.residual_embeddings as residual_embeddings

from primeqa.ir.dense.colbert_top.colbert.search.strided_tensor import StridedTensor

"""
import line_profiler
import atexit
profile = line_profiler.LineProfiler()
atexit.register(profile.print_stats)
"""


class ResidualEmbeddingsStrided:
    def __init__(self, codec, embeddings, doclens):
        self.codec = codec
        self.codes = embeddings.codes
        self.residuals = embeddings.residuals

        self.codes_strided = StridedTensor(self.codes, doclens)
        self.residuals_strided = StridedTensor(self.residuals, doclens)

    def lookup_eids(self, embedding_ids, codes=None, out_device='cuda'):
        codes = self.codes[embedding_ids] if codes is None else codes
        residuals = self.residuals[embedding_ids]

        return self.codec.decompress(residual_embeddings.ResidualEmbeddings(codes, residuals))

    # # @profile
    def lookup_pids(self, passage_ids, out_device='cuda'):
        codes_packed, codes_lengths = self.codes_strided.lookup(passage_ids)#.as_packed_tensor()
        residuals_packed, _ = self.residuals_strided.lookup(passage_ids)#.as_packed_tensor()

        embeddings_packed = self.codec.decompress(residual_embeddings.ResidualEmbeddings(codes_packed, residuals_packed))

        return embeddings_packed, codes_lengths
        # return StridedTensor(embeddings_packed, codes_lengths).as_padded_tensor()
        # return StridedTensor.pad_packed(embeddings_packed, codes_lengths)
