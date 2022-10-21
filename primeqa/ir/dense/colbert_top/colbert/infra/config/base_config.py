import os
import dataclasses

import ujson

from primeqa.ir.dense.colbert_top.colbert.utils.utils import torch_load_dnn
from primeqa.ir.dense.colbert_top.utility.utils.save_metadata import get_metadata_only
from primeqa.ir.dense.colbert_top.colbert.utils.utils import print_message
from .core_config import CoreConfig


@dataclasses.dataclass
class BaseConfig(CoreConfig):
    @classmethod
    def from_existing(cls, *sources):
        kw_args = {}

        for source in sources:
            if source is None:
                continue

            local_kw_args = dataclasses.asdict(source)
            local_kw_args = {k: local_kw_args[k] for k in source.assigned}
            kw_args = {**kw_args, **local_kw_args}

        obj = cls(**kw_args)

        return obj

    @classmethod
    def from_deprecated_args(cls, args):
        obj = cls()
        ignored = obj.configure(ignore_unrecognized=True, **args)

        return obj, ignored

    @classmethod
    def from_path(cls, name):

        print_message(f"#> base_config.py from_path: {name}")
        with open(name, "r", encoding="utf-8") as filename:
            args = ujson.load(filename)

            if "config" in args:
                args = args["config"]

        return cls.from_deprecated_args(
            args
        )  # the new, non-deprecated version functions the same at this level.

    @classmethod
    def load_from_checkpoint(cls, checkpoint_path):
        if checkpoint_path.endswith(".dnn") or checkpoint_path.endswith(".model"):
            dnn = torch_load_dnn(checkpoint_path)
            config, _ = cls.from_deprecated_args(dnn.get("arguments", {}))

            # get model type from a dnn file
            if dnn["model_type"] is not None:
                config.set("model_type", dnn["model_type"])

            config.set("checkpoint", checkpoint_path)

            return config

        loaded_config_path = os.path.join(checkpoint_path, "artifact.metadata")

        print_message(f"#> base_config.py from_checkpoint: {checkpoint_path}")
        print_message(f"#> base_config.py from_checkpoint_config: {loaded_config_path}")

        if os.path.exists(loaded_config_path):
            loaded_config, _ = cls.from_path(loaded_config_path)
            loaded_config.set("checkpoint", checkpoint_path)

            return loaded_config

        return (
            None  # can happen if checkpoint_path is something like 'bert-base-uncased'
        )

    @classmethod
    def load_from_index(cls, index_path):
        # FIXME: We should start here with initial_config = ColBERTConfig(config, Run().config).
        # This should allow us to say initial_config.index_root. Then, below, set config = Config(..., initial_c)

        # default_index_root = os.path.join(Run().root, Run().experiment, 'indexes/')
        # index_path = os.path.join(default_index_root, index_path)

        # CONSIDER: No more plan/metadata.json. Only metadata.json to avoid weird issues when loading an index.

        try:
            metadata_path = os.path.join(index_path, "metadata.json")
            loaded_config, _ = cls.from_path(metadata_path)
        except FileNotFoundError:
            metadata_path = os.path.join(index_path, "plan.json")
            loaded_config, _ = cls.from_path(metadata_path)

        return loaded_config

    def save(self, path, overwrite=False):
        assert overwrite or not os.path.exists(path), path

        with open(path, "w", encoding="utf-8") as f:
            args = self.export()  # dict(self.__config)
            args["meta"] = get_metadata_only()
            args["meta"]["version"] = "colbert-v0.4"
            # TODO: Add git_status details.. It can't be too large! It should be a path that Runs() saves on exit, maybe!

            f.write(ujson.dumps(args, indent=4) + "\n")

    def save_for_checkpoint(self, checkpoint_path):
        assert not checkpoint_path.endswith(
            ".dnn"
        ), f"{checkpoint_path}: We reserve *.dnn names for the deprecated checkpoint format."

        output_config_path = os.path.join(checkpoint_path, "artifact.metadata")
        self.save(output_config_path, overwrite=True)
