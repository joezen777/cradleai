# Cradle AI

# The Goal

They say a picture is worth a thousand words, so what are the best 1000 words?  I'm a huge Cradle fan so when I saw the animatic come out, I thought, here's a good chance to test out how this process and see if I could figure out how to optimize it.  

On one side:

SOURCE IMAGE PERSON -> IMAGE_TO_TEXT_LLM ==> TEXT ==> TEXT_TO_IMAGE -> SIMILAR LOOKING PERSON

But in this case it's

SOURCE STORYBOOK FRAME -> IMAGE_TO_TEXT_LLM ==> TEXT ==>  GROUND_IN_LORE ==> TEXT_TO_IMAGE -> LIVE ACTION VERSION

And finally, if I figure out a cheap way, do a FLF-Text => Video

I'm running this on my WSL2 Ubuntu 24 on my i7 6 core RTX 5070 12GB VRAM 64GB RAM home AI box. 

I've experimented the most with zimageturbo for the image.  

In my first iteration I was using Gemini to do my lore grounding, but then I though to create my own vector database and use local LLM both for grounding and for fixed optimization of the final prompt for the zimageturbo model. $8 on 1600 batches against your GCP account will make you think twice, and after a couple of days a 30 day forecast of $172 will make you think thrice. 




## Run the main pipeline

From the project root:

```bash
ALLOW_GEMINI=YES python run_complete_pipeline.py --batch_name zimageturbo --num_copies 10
```

The pipeline is resumable: rerunning this command preserves completed metadata and generated frames, then continues with outstanding work.
