# MRBench MathDial sample attribution

`mrbench_mathdial_v1_sample.jsonl` is a filtered, JSONL-formatted derivative of [MRBench V1](https://github.com/kaushal0494/UnifyingAITutorEvaluation/blob/main/MRBench/MRBench_V1.json), by Kaushal Kumar Maurya, KV Aditya Srivatsa, Kseniia Petukhova, and Ekaterina Kochmar. The MRBench creators release it under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). This derived sample is distributed under the same license. Changes: retained only the first four `Data == MathDial` and `Split == test` dialogues in upstream order; converted the selected JSON objects to JSONL. Original human annotations and tutor responses remain attached to each dialogue.

The underlying [MathDial dataset](https://huggingface.co/datasets/eth-nlped/mathdial) is published by the ETH Zurich Language, Reasoning and Education lab with [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) metadata. No Bridge-origin rows are included in this sample. See `mrbench_mathdial_v1_sample.meta.json` for the upstream blob SHA, sample SHA-256, selected count, and citation.

This is a four-dialogue adapter and judge calibration sample from mathematics tutoring. It is not a writing-tutor benchmark and does not establish product effectiveness.
