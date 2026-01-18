使用gemini-2.5-flash

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="<OPENROUTER_API_KEY>",
)

completion = client.chat.completions.create(
    extra_headers={
        "HTTP-Referer": "<YOUR_SITE_URL>", # Optional. Site URL for rankings on openrouter.ai.
        "X-Title": "<YOUR_SITE_NAME>", # Optional. Site title for rankings on openrouter.ai.
    },
    extra_body={},
    model="google/gemini-2.5-flash",
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "What is in this image, audio and video?"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://live.staticflickr.com/3851/14825276609_098cac593d_b.jpg"
                    }
                },
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": "UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB",
                        "format": "wav"
                    }
                },
                {
                    "type": "video_url",
                    "video_url": {
                        "url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/1080/Big_Buck_Bunny_1080_10s_5MB.mp4"
                    }
                }
            ]
        }
    ]
)
print(completion.choices[0].message.content)
```

使用grop
```python
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="<OPENROUTER_API_KEY>",
)

completion = client.chat.completions.create(
    extra_headers={
        "HTTP-Referer": "<YOUR_SITE_URL>", # Optional. Site URL for rankings on openrouter.ai.
        "X-Title": "<YOUR_SITE_NAME>", # Optional. Site title for rankings on openrouter.ai.
    },
    extra_body={},
    model="x-ai/grok-code-fast-1",
    messages=[
        {
            "role": "user",
            "content": "What is the meaning of life?"
        }
    ]
)
print(completion.choices[0].message.content)
```