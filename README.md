# Cradle AI

## Run the main pipeline

From the project root:

```bash
ALLOW_GEMINI=YES python run_complete_pipeline.py --batch_name zimageturbo --num_copies 10
```

The pipeline is resumable: rerunning this command preserves completed metadata and generated frames, then continues with outstanding work.
