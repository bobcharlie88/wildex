# Offline Gemma Dr Agent

The WildEx Dr Agent can run on a local Google Gemma model through Hugging Face
Transformers. It is lazy-loaded the first time `/dr/ask` runs, so app startup
stays light.

## Environment

Add these values to `.env` on the machine that will run the game:

```env
DR_AGENT_ENGINE=gemma
DR_GEMMA_MODEL=models/gemma-2-2b-it
DR_GEMMA_LOCAL_FILES_ONLY=true
DR_GEMMA_MAX_NEW_TOKENS=220
```

For a fully offline machine, download the Gemma model once on a connected
machine, accept the Gemma license on Hugging Face if required, then copy the
model folder or Hugging Face cache to the game machine. Set `DR_GEMMA_MODEL` to
that local folder path, for example:

```env
DR_GEMMA_MODEL=M:\Wildex_Transfer\models\gemma-2-2b-it
DR_GEMMA_LOCAL_FILES_ONLY=true
```

If you prefer to use the Hugging Face cache directly, set `DR_GEMMA_MODEL` to
the Gemma repo ID after the files are already cached:

```env
DR_GEMMA_MODEL=google/gemma-2-2b-it
DR_GEMMA_LOCAL_FILES_ONLY=true
```

If the local model cannot be loaded, the Dr Agent automatically falls back to
the existing rule-based response builder so gameplay still works.

## Notes

- `transformers`, `torch`, and `accelerate` are required in `requirements.txt`.
- The default `local_files_only=true` prevents accidental internet downloads.
- Gemma models are large. Use a small instruction-tuned model for laptops or
  handheld/offline field machines.
