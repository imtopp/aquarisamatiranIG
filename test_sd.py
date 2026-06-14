import torch, time
from diffusers import StableDiffusionPipeline

model_id = "runwayml/stable-diffusion-v1-5"
print(f"Loading {model_id} on CPU... (this may take a while)")
t0 = time.time()
pipe = StableDiffusionPipeline.from_pretrained(model_id, torch_dtype=torch.float32)
print(f"Model loaded in {time.time()-t0:.1f}s")

prompt = "aquarium with green plants and rocks, underwater scene, high quality"
print(f"Generating: {prompt}")
t0 = time.time()
image = pipe(prompt, num_inference_steps=20).images[0]
print(f"Generated in {time.time()-t0:.1f}s")
image.save("test_sd_output.png")
print("Saved test_sd_output.png")
print(f"Size: {image.size}")
