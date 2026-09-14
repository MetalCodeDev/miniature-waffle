# Gemini Media Module
# Creator: @mxzavo

import os
import base64
from google import genai

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


async def generate_image(prompt: str):
    response = client.interactions.create(
        model="gemini-3.1-flash-image",
        input=prompt
    )

    if not response.output_image:
        raise RuntimeError("Gemini не вернул изображение")

    image_data = base64.b64decode(response.output_image.data)

    with open("generated.png", "wb") as file:
        file.write(image_data)

    return "generated.png"
