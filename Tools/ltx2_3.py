"""
title: LTX-2.3 Video Generator (T2V + I2V)
description: >
  Two separate tools the LLM can call:
    • generate_video_t2v  – Text-to-Video   (no image needed)
    • generate_video_i2v  – Image-to-Video  (animates an uploaded image)
  Both use LTX-Video 2.3 via ComfyUI, randomise seeds, unload Ollama and/or
  llama.cpp VRAM, and embed the finished video directly in chat.
author: ichrist, adapted from Haervwe's ComfyUI T2V Tool
version: 3.1.0
license: MIT

HOW IMAGE PASSING ACTUALLY WORKS IN OPEN WEBUI
===============================================
When a user uploads an image, OWUI sends it to the LLM as a multimodal
message content item:
  { "type": "image_url", "image_url": { "url": "data:image/png;base64,..." } }
  or
  { "type": "image_url", "image_url": { "url": "/api/v1/files/{id}/content" } }

The LLM sees this URL and, when calling a tool, must pass it as a regular
string argument called image_url.  __files__ is for document attachments
(PDFs, text files for RAG) — it is NOT populated for vision/inline images.

Fix strategy for generate_video_i2v:
  1. Accept image_url: str as an explicit LLM-filled parameter.
  2. Also accept __messages__ and scan the conversation for image_url blocks
     as a fallback for when the LLM forgets to forward the argument.
  3. Handle all three URL formats:
       a. data:image/...;base64,<b64>  → decode directly
       b. /api/v1/files/{id}/content  → GET from localhost (OWUI internal)
       c. http(s)://...               → GET directly
"""

import aiohttp
import asyncio
import json
import random
import uuid
import os
import io
import logging
import base64
import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Callable, Awaitable, cast
from urllib.parse import quote
from pydantic import BaseModel, Field
from fastapi import UploadFile
from open_webui.models.users import Users
from open_webui.routers.files import upload_file_handler  # type: ignore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov")

OWUI_INTERNAL_BASE = os.environ.get("OWUI_INTERNAL_BASE", "http://localhost:8080")


# ═══════════════════════════════════════════════════════════════════════════════
#  Workflow templates
# ═══════════════════════════════════════════════════════════════════════════════

T2V_WORKFLOW: Dict[str, Any] = {
    "75": {
        "inputs": {
            "filename_prefix": "video/LTX_2.3_t2v",
            "format": "mp4",
            "codec": "auto",
            "video": ["276", 0],
        },
        "class_type": "SaveVideo",
        "_meta": {"title": "Save Video"},
    },
    "269": {
        "inputs": {"image": "example.png"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"},
    },
    "276": {
        "inputs": {"value": ["267:242", 0]},
        "class_type": "UnloadAllModels",
        "_meta": {"title": "UnloadAllModels"},
    },
    "267:216": {
        "inputs": {"noise_seed": 42},
        "class_type": "RandomNoise",
        "_meta": {"title": "RandomNoise"},
    },
    "267:237": {
        "inputs": {"noise_seed": 731987174230470},
        "class_type": "RandomNoise",
        "_meta": {"title": "RandomNoise"},
    },
    "267:229": {
        "inputs": {"video_latent": ["267:230", 0], "audio_latent": ["267:217", 1]},
        "class_type": "LTXVConcatAVLatent",
        "_meta": {"title": "LTXVConcatAVLatent"},
    },
    "267:221": {
        "inputs": {"ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors"},
        "class_type": "LTXVAudioVAELoader",
        "_meta": {"title": "LTXV Audio VAE Loader"},
    },
    "267:246": {
        "inputs": {"sampler_name": "euler_cfg_pp"},
        "class_type": "KSamplerSelect",
        "_meta": {"title": "KSamplerSelect"},
    },
    "267:211": {
        "inputs": {"sigmas": "0.85, 0.7250, 0.4219, 0.0"},
        "class_type": "ManualSigmas",
        "_meta": {"title": "ManualSigmas"},
    },
    "267:213": {
        "inputs": {
            "cfg": 1,
            "model": ["267:232", 0],
            "positive": ["267:212", 0],
            "negative": ["267:212", 1],
        },
        "class_type": "CFGGuider",
        "_meta": {"title": "CFGGuider"},
    },
    "267:215": {
        "inputs": {
            "noise": ["267:237", 0],
            "guider": ["267:231", 0],
            "sampler": ["267:209", 0],
            "sigmas": ["267:252", 0],
            "latent_image": ["267:222", 0],
        },
        "class_type": "SamplerCustomAdvanced",
        "_meta": {"title": "SamplerCustomAdvanced"},
    },
    "267:212": {
        "inputs": {
            "positive": ["267:239", 0],
            "negative": ["267:239", 1],
            "latent": ["267:217", 0],
        },
        "class_type": "LTXVCropGuides",
        "_meta": {"title": "LTXVCropGuides"},
    },
    "267:232": {
        "inputs": {
            "lora_name": "ltx-2.3-22b-distilled-lora-384.safetensors",
            "strength_model": 0.5,
            "model": ["267:236", 0],
        },
        "class_type": "LoraLoaderModelOnly",
        "_meta": {"title": "Load LoRA"},
    },
    "267:235": {
        "inputs": {"longer_edge": 1536, "images": ["267:238", 0]},
        "class_type": "ResizeImagesByLongerEdge",
        "_meta": {"title": "Resize Images by Longer Edge"},
    },
    "267:253": {
        "inputs": {
            "samples": ["267:217", 0],
            "upscale_model": ["267:233", 0],
            "vae": ["267:236", 2],
        },
        "class_type": "LTXVLatentUpsampler",
        "_meta": {"title": "LTXVLatentUpsampler"},
    },
    "267:230": {
        "inputs": {
            "strength": 1,
            "bypass": ["267:201", 0],
            "vae": ["267:236", 2],
            "image": ["267:248", 0],
            "latent": ["267:253", 0],
        },
        "class_type": "LTXVImgToVideoInplace",
        "_meta": {"title": "LTXVImgToVideoInplace"},
    },
    "267:248": {
        "inputs": {"img_compression": 18, "image": ["267:235", 0]},
        "class_type": "LTXVPreprocess",
        "_meta": {"title": "LTXVPreprocess"},
    },
    "267:238": {
        "inputs": {
            "resize_type": "scale dimensions",
            "resize_type.width": ["267:257", 0],
            "resize_type.height": ["267:258", 0],
            "resize_type.crop": "center",
            "scale_method": "lanczos",
            "input": ["269", 0],
        },
        "class_type": "ResizeImageMaskNode",
        "_meta": {"title": "Resize Image/Mask"},
    },
    "267:209": {
        "inputs": {"sampler_name": "euler_ancestral_cfg_pp"},
        "class_type": "KSamplerSelect",
        "_meta": {"title": "KSamplerSelect"},
    },
    "267:256": {
        "inputs": {"expression": "a/2", "values.a": ["267:257", 0]},
        "class_type": "ComfyMathExpression",
        "_meta": {"title": "Math Expression"},
    },
    "267:259": {
        "inputs": {"expression": "a/2", "values.a": ["267:258", 0]},
        "class_type": "ComfyMathExpression",
        "_meta": {"title": "Math Expression"},
    },
    "267:228": {
        "inputs": {
            "width": ["267:256", 1],
            "height": ["267:259", 1],
            "length": ["267:225", 0],
            "batch_size": 1,
        },
        "class_type": "EmptyLTXVLatentVideo",
        "_meta": {"title": "EmptyLTXVLatentVideo"},
    },
    "267:249": {
        "inputs": {
            "strength": 0.7,
            "bypass": ["267:201", 0],
            "vae": ["267:236", 2],
            "image": ["267:248", 0],
            "latent": ["267:228", 0],
        },
        "class_type": "LTXVImgToVideoInplace",
        "_meta": {"title": "LTXVImgToVideoInplace"},
    },
    "267:220": {
        "inputs": {"samples": ["267:218", 1], "audio_vae": ["267:221", 0]},
        "class_type": "LTXVAudioVAEDecode",
        "_meta": {"title": "LTXV Audio VAE Decode"},
    },
    "267:261": {
        "inputs": {"expression": "a", "values.a": ["267:260", 0]},
        "class_type": "ComfyMathExpression",
        "_meta": {"title": "Math Expression"},
    },
    "267:258": {
        "inputs": {"value": 720},
        "class_type": "PrimitiveInt",
        "_meta": {"title": "Height"},
    },
    "267:260": {
        "inputs": {"value": 24},
        "class_type": "PrimitiveInt",
        "_meta": {"title": "Frame Rate"},
    },
    "267:225": {
        "inputs": {"value": 121},
        "class_type": "PrimitiveInt",
        "_meta": {"title": "Length"},
    },
    "267:201": {
        "inputs": {"value": True},
        "class_type": "PrimitiveBoolean",
        "_meta": {"title": "Switch to Text to Video?"},
    },
    "267:240": {
        "inputs": {"text": ["267:274", 0], "clip": ["267:243", 0]},
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "CLIP Text Encode (Prompt)"},
    },
    "267:239": {
        "inputs": {
            "frame_rate": ["267:261", 0],
            "positive": ["267:240", 0],
            "negative": ["267:247", 0],
        },
        "class_type": "LTXVConditioning",
        "_meta": {"title": "LTXVConditioning"},
    },
    "267:214": {
        "inputs": {
            "frames_number": ["267:225", 0],
            "frame_rate": ["267:261", 1],
            "batch_size": 1,
            "audio_vae": ["267:221", 0],
        },
        "class_type": "LTXVEmptyLatentAudio",
        "_meta": {"title": "LTXV Empty Latent Audio"},
    },
    "267:252": {
        "inputs": {
            "sigmas": "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
        },
        "class_type": "ManualSigmas",
        "_meta": {"title": "ManualSigmas"},
    },
    "267:217": {
        "inputs": {"av_latent": ["267:215", 0]},
        "class_type": "LTXVSeparateAVLatent",
        "_meta": {"title": "LTXVSeparateAVLatent"},
    },
    "267:219": {
        "inputs": {
            "noise": ["267:216", 0],
            "guider": ["267:213", 0],
            "sampler": ["267:246", 0],
            "sigmas": ["267:211", 0],
            "latent_image": ["267:229", 0],
        },
        "class_type": "SamplerCustomAdvanced",
        "_meta": {"title": "SamplerCustomAdvanced"},
    },
    "267:218": {
        "inputs": {"av_latent": ["267:219", 0]},
        "class_type": "LTXVSeparateAVLatent",
        "_meta": {"title": "LTXVSeparateAVLatent"},
    },
    "267:242": {
        "inputs": {
            "fps": ["267:261", 0],
            "images": ["267:251", 0],
            "audio": ["267:220", 0],
        },
        "class_type": "CreateVideo",
        "_meta": {"title": "Create Video"},
    },
    "267:233": {
        "inputs": {"model_name": "ltx-2.3-spatial-upscaler-x2-1.0.safetensors"},
        "class_type": "LatentUpscaleModelLoader",
        "_meta": {"title": "Load Latent Upscale Model"},
    },
    "267:257": {
        "inputs": {"value": 1280},
        "class_type": "PrimitiveInt",
        "_meta": {"title": "Width"},
    },
    "267:247": {
        "inputs": {
            "text": "pc game, console game, video game, cartoon, childish, ugly",
            "clip": ["267:272", 1],
        },
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "CLIP Text Encode (Prompt)"},
    },
    "267:231": {
        "inputs": {
            "cfg": 1,
            "model": ["267:232", 0],
            "positive": ["267:239", 0],
            "negative": ["267:239", 1],
        },
        "class_type": "CFGGuider",
        "_meta": {"title": "CFGGuider"},
    },
    "267:251": {
        "inputs": {
            "tile_size": 768,
            "overlap": 64,
            "temporal_size": 4096,
            "temporal_overlap": 4,
            "samples": ["267:218", 0],
            "vae": ["267:236", 2],
        },
        "class_type": "VAEDecodeTiled",
        "_meta": {"title": "VAE Decode (Tiled)"},
    },
    "267:236": {
        "inputs": {"ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors"},
        "class_type": "CheckpointLoaderSimple",
        "_meta": {"title": "Load Checkpoint"},
    },
    "267:243": {
        "inputs": {
            "text_encoder": "gemma_3_12B_it_fp4_mixed.safetensors",
            "ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors",
            "device": "default",
        },
        "class_type": "LTXAVTextEncoderLoader",
        "_meta": {"title": "LTXV Audio Text Encoder Loader"},
    },
    "267:266": {
        "inputs": {"value": ""},
        "class_type": "PrimitiveStringMultiline",
        "_meta": {"title": "Prompt"},
    },
    "267:274": {
        "inputs": {
            "prompt": ["267:266", 0],
            "max_length": 256,
            "sampling_mode": "on",
            "sampling_mode.temperature": 0.7,
            "sampling_mode.top_k": 64,
            "sampling_mode.top_p": 0.95,
            "sampling_mode.min_p": 0.05,
            "sampling_mode.repetition_penalty": 1.05,
            "sampling_mode.seed": 0,
            "clip": ["267:272", 1],
        },
        "class_type": "TextGenerateLTX2Prompt",
        "_meta": {"title": "TextGenerateLTX2Prompt"},
    },
    "267:275": {
        "inputs": {"preview": "", "previewMode": None, "source": ["267:274", 0]},
        "class_type": "PreviewAny",
        "_meta": {"title": "Preview as Text"},
    },
    "267:272": {
        "inputs": {
            "lora_name": "gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors",
            "strength_model": 1,
            "strength_clip": 1,
            "model": ["267:236", 0],
            "clip": ["267:243", 0],
        },
        "class_type": "LoraLoader",
        "_meta": {"title": "Load LoRA (Model and CLIP)"},
    },
    "267:222": {
        "inputs": {"video_latent": ["267:249", 0], "audio_latent": ["267:214", 0]},
        "class_type": "LTXVConcatAVLatent",
        "_meta": {"title": "LTXVConcatAVLatent"},
    },
}

I2V_WORKFLOW: Dict[str, Any] = {
    "75": {
        "inputs": {
            "filename_prefix": "video/LTX_2.3_i2v",
            "format": "mp4",
            "codec": "auto",
            "video": ["277", 0],
        },
        "class_type": "SaveVideo",
        "_meta": {"title": "Save Video"},
    },
    "269": {
        "inputs": {"image": "example.png"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"},
    },
    "276": {
        "inputs": {"image": ["269", 0]},
        "class_type": "GetImageSize",
        "_meta": {"title": "Get Image Size"},
    },
    "277": {
        "inputs": {"value": ["267:242", 0]},
        "class_type": "UnloadAllModels",
        "_meta": {"title": "UnloadAllModels"},
    },
    "267:216": {
        "inputs": {"noise_seed": 42},
        "class_type": "RandomNoise",
        "_meta": {"title": "RandomNoise"},
    },
    "267:237": {
        "inputs": {"noise_seed": 456318206358524},
        "class_type": "RandomNoise",
        "_meta": {"title": "RandomNoise"},
    },
    "267:229": {
        "inputs": {"video_latent": ["267:230", 0], "audio_latent": ["267:217", 1]},
        "class_type": "LTXVConcatAVLatent",
        "_meta": {"title": "LTXVConcatAVLatent"},
    },
    "267:221": {
        "inputs": {"ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors"},
        "class_type": "LTXVAudioVAELoader",
        "_meta": {"title": "LTXV Audio VAE Loader"},
    },
    "267:246": {
        "inputs": {"sampler_name": "euler_cfg_pp"},
        "class_type": "KSamplerSelect",
        "_meta": {"title": "KSamplerSelect"},
    },
    "267:211": {
        "inputs": {"sigmas": "0.85, 0.7250, 0.4219, 0.0"},
        "class_type": "ManualSigmas",
        "_meta": {"title": "ManualSigmas"},
    },
    "267:213": {
        "inputs": {
            "cfg": 1,
            "model": ["267:232", 0],
            "positive": ["267:212", 0],
            "negative": ["267:212", 1],
        },
        "class_type": "CFGGuider",
        "_meta": {"title": "CFGGuider"},
    },
    "267:215": {
        "inputs": {
            "noise": ["267:237", 0],
            "guider": ["267:231", 0],
            "sampler": ["267:209", 0],
            "sigmas": ["267:252", 0],
            "latent_image": ["267:222", 0],
        },
        "class_type": "SamplerCustomAdvanced",
        "_meta": {"title": "SamplerCustomAdvanced"},
    },
    "267:212": {
        "inputs": {
            "positive": ["267:239", 0],
            "negative": ["267:239", 1],
            "latent": ["267:217", 0],
        },
        "class_type": "LTXVCropGuides",
        "_meta": {"title": "LTXVCropGuides"},
    },
    "267:232": {
        "inputs": {
            "lora_name": "ltx-2.3-22b-distilled-lora-384.safetensors",
            "strength_model": 0.5,
            "model": ["267:236", 0],
        },
        "class_type": "LoraLoaderModelOnly",
        "_meta": {"title": "Load LoRA"},
    },
    "267:235": {
        "inputs": {"longer_edge": 1536, "images": ["267:238", 0]},
        "class_type": "ResizeImagesByLongerEdge",
        "_meta": {"title": "Resize Images by Longer Edge"},
    },
    "267:253": {
        "inputs": {
            "samples": ["267:217", 0],
            "upscale_model": ["267:233", 0],
            "vae": ["267:236", 2],
        },
        "class_type": "LTXVLatentUpsampler",
        "_meta": {"title": "LTXVLatentUpsampler"},
    },
    "267:230": {
        "inputs": {
            "strength": 1,
            "bypass": ["267:201", 0],
            "vae": ["267:236", 2],
            "image": ["267:248", 0],
            "latent": ["267:253", 0],
        },
        "class_type": "LTXVImgToVideoInplace",
        "_meta": {"title": "LTXVImgToVideoInplace"},
    },
    "267:248": {
        "inputs": {"img_compression": 18, "image": ["267:235", 0]},
        "class_type": "LTXVPreprocess",
        "_meta": {"title": "LTXVPreprocess"},
    },
    "267:238": {
        "inputs": {
            "resize_type": "scale dimensions",
            "resize_type.width": ["267:257", 0],
            "resize_type.height": ["267:258", 0],
            "resize_type.crop": "center",
            "scale_method": "lanczos",
            "input": ["269", 0],
        },
        "class_type": "ResizeImageMaskNode",
        "_meta": {"title": "Resize Image/Mask"},
    },
    "267:209": {
        "inputs": {"sampler_name": "euler_ancestral_cfg_pp"},
        "class_type": "KSamplerSelect",
        "_meta": {"title": "KSamplerSelect"},
    },
    "267:256": {
        "inputs": {"expression": "a/2", "values.a": ["267:257", 0]},
        "class_type": "ComfyMathExpression",
        "_meta": {"title": "Math Expression"},
    },
    "267:259": {
        "inputs": {"expression": "a/2", "values.a": ["267:258", 0]},
        "class_type": "ComfyMathExpression",
        "_meta": {"title": "Math Expression"},
    },
    "267:228": {
        "inputs": {
            "width": ["267:256", 1],
            "height": ["267:259", 1],
            "length": ["267:225", 0],
            "batch_size": 1,
        },
        "class_type": "EmptyLTXVLatentVideo",
        "_meta": {"title": "EmptyLTXVLatentVideo"},
    },
    "267:249": {
        "inputs": {
            "strength": 0.7,
            "bypass": ["267:201", 0],
            "vae": ["267:236", 2],
            "image": ["267:248", 0],
            "latent": ["267:228", 0],
        },
        "class_type": "LTXVImgToVideoInplace",
        "_meta": {"title": "LTXVImgToVideoInplace"},
    },
    "267:220": {
        "inputs": {"samples": ["267:218", 1], "audio_vae": ["267:221", 0]},
        "class_type": "LTXVAudioVAEDecode",
        "_meta": {"title": "LTXV Audio VAE Decode"},
    },
    "267:261": {
        "inputs": {"expression": "a", "values.a": ["267:260", 0]},
        "class_type": "ComfyMathExpression",
        "_meta": {"title": "Math Expression"},
    },
    "267:258": {
        "inputs": {"value": ["276", 1]},
        "class_type": "PrimitiveInt",
        "_meta": {"title": "Height"},
    },
    "267:260": {
        "inputs": {"value": 24},
        "class_type": "PrimitiveInt",
        "_meta": {"title": "Frame Rate"},
    },
    "267:225": {
        "inputs": {"value": 121},
        "class_type": "PrimitiveInt",
        "_meta": {"title": "Length"},
    },
    "267:201": {
        "inputs": {"value": False},
        "class_type": "PrimitiveBoolean",
        "_meta": {"title": "Switch to Text to Video?"},
    },
    "267:240": {
        "inputs": {"text": ["267:274", 0], "clip": ["267:243", 0]},
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "CLIP Text Encode (Prompt)"},
    },
    "267:239": {
        "inputs": {
            "frame_rate": ["267:261", 0],
            "positive": ["267:240", 0],
            "negative": ["267:247", 0],
        },
        "class_type": "LTXVConditioning",
        "_meta": {"title": "LTXVConditioning"},
    },
    "267:214": {
        "inputs": {
            "frames_number": ["267:225", 0],
            "frame_rate": ["267:261", 1],
            "batch_size": 1,
            "audio_vae": ["267:221", 0],
        },
        "class_type": "LTXVEmptyLatentAudio",
        "_meta": {"title": "LTXV Empty Latent Audio"},
    },
    "267:252": {
        "inputs": {
            "sigmas": "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
        },
        "class_type": "ManualSigmas",
        "_meta": {"title": "ManualSigmas"},
    },
    "267:217": {
        "inputs": {"av_latent": ["267:215", 0]},
        "class_type": "LTXVSeparateAVLatent",
        "_meta": {"title": "LTXVSeparateAVLatent"},
    },
    "267:219": {
        "inputs": {
            "noise": ["267:216", 0],
            "guider": ["267:213", 0],
            "sampler": ["267:246", 0],
            "sigmas": ["267:211", 0],
            "latent_image": ["267:229", 0],
        },
        "class_type": "SamplerCustomAdvanced",
        "_meta": {"title": "SamplerCustomAdvanced"},
    },
    "267:218": {
        "inputs": {"av_latent": ["267:219", 0]},
        "class_type": "LTXVSeparateAVLatent",
        "_meta": {"title": "LTXVSeparateAVLatent"},
    },
    "267:242": {
        "inputs": {
            "fps": ["267:261", 0],
            "images": ["267:251", 0],
            "audio": ["267:220", 0],
        },
        "class_type": "CreateVideo",
        "_meta": {"title": "Create Video"},
    },
    "267:233": {
        "inputs": {"model_name": "ltx-2.3-spatial-upscaler-x2-1.0.safetensors"},
        "class_type": "LatentUpscaleModelLoader",
        "_meta": {"title": "Load Latent Upscale Model"},
    },
    "267:257": {
        "inputs": {"value": ["276", 0]},
        "class_type": "PrimitiveInt",
        "_meta": {"title": "Width"},
    },
    "267:247": {
        "inputs": {
            "text": "pc game, console game, video game, cartoon, childish, ugly",
            "clip": ["267:272", 1],
        },
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "CLIP Text Encode (Prompt)"},
    },
    "267:231": {
        "inputs": {
            "cfg": 1,
            "model": ["267:232", 0],
            "positive": ["267:239", 0],
            "negative": ["267:239", 1],
        },
        "class_type": "CFGGuider",
        "_meta": {"title": "CFGGuider"},
    },
    "267:251": {
        "inputs": {
            "tile_size": 768,
            "overlap": 64,
            "temporal_size": 4096,
            "temporal_overlap": 4,
            "samples": ["267:218", 0],
            "vae": ["267:236", 2],
        },
        "class_type": "VAEDecodeTiled",
        "_meta": {"title": "VAE Decode (Tiled)"},
    },
    "267:236": {
        "inputs": {"ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors"},
        "class_type": "CheckpointLoaderSimple",
        "_meta": {"title": "Load Checkpoint"},
    },
    "267:243": {
        "inputs": {
            "text_encoder": "gemma_3_12B_it_fp4_mixed.safetensors",
            "ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors",
            "device": "default",
        },
        "class_type": "LTXAVTextEncoderLoader",
        "_meta": {"title": "LTXV Audio Text Encoder Loader"},
    },
    "267:266": {
        "inputs": {"value": ""},
        "class_type": "PrimitiveStringMultiline",
        "_meta": {"title": "Prompt"},
    },
    "267:274": {
        "inputs": {
            "prompt": ["267:266", 0],
            "max_length": 256,
            "sampling_mode": "on",
            "sampling_mode.temperature": 0.7,
            "sampling_mode.top_k": 64,
            "sampling_mode.top_p": 0.95,
            "sampling_mode.min_p": 0.05,
            "sampling_mode.repetition_penalty": 1.05,
            "sampling_mode.seed": 0,
            "clip": ["267:272", 1],
        },
        "class_type": "TextGenerateLTX2Prompt",
        "_meta": {"title": "TextGenerateLTX2Prompt"},
    },
    "267:275": {
        "inputs": {"preview": "", "previewMode": None, "source": ["267:274", 0]},
        "class_type": "PreviewAny",
        "_meta": {"title": "Preview as Text"},
    },
    "267:272": {
        "inputs": {
            "lora_name": "gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors",
            "strength_model": 1,
            "strength_clip": 1,
            "model": ["267:236", 0],
            "clip": ["267:243", 0],
        },
        "class_type": "LoraLoader",
        "_meta": {"title": "Load LoRA (Model and CLIP)"},
    },
    "267:222": {
        "inputs": {"video_latent": ["267:249", 0], "audio_latent": ["267:214", 0]},
        "class_type": "LTXVConcatAVLatent",
        "_meta": {"title": "LTXVConcatAVLatent"},
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Image resolution helpers
# ═══════════════════════════════════════════════════════════════════════════════


async def _bytes_from_url(url: str, owui_base: str) -> Optional[bytes]:
    """
    Fetch image bytes from any URL form OWUI uses:
      1. data:image/...;base64,<b64>  — decode directly
      2. /api/v1/files/{id}/content  — GET from localhost (OWUI internal)
      3. http(s)://...               — GET directly
    """
    if not url:
        return None

    # 1. Inline base64 data URI
    if url.startswith("data:"):
        try:
            payload = url.split(",", 1)[1]
            data = base64.b64decode(payload)
            logger.info("Image decoded from inline base64 (%d bytes)", len(data))
            return data
        except Exception as e:
            logger.warning("base64 decode failed: %s", e)
            return None

    # 2. OWUI-relative path
    if url.startswith("/"):
        full = owui_base.rstrip("/") + url
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(full) as r:
                    if r.status == 200:
                        data = await r.read()
                        logger.info(
                            "Image fetched from OWUI internal %s (%d bytes)",
                            url,
                            len(data),
                        )
                        return data
                    logger.warning("OWUI internal fetch %s → HTTP %d", url, r.status)
        except Exception as e:
            logger.warning("OWUI internal fetch error for %s: %s", url, e)
        return None

    # 3. Absolute HTTP(S) URL
    if url.startswith("http://") or url.startswith("https://"):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        data = await r.read()
                        logger.info(
                            "Image fetched from absolute URL (%d bytes)", len(data)
                        )
                        return data
                    logger.warning("Absolute URL fetch → HTTP %d", r.status)
        except Exception as e:
            logger.warning("Absolute URL fetch error: %s", e)
        return None

    logger.warning("Unrecognised image_url format: %.80s", url)
    return None


def _extract_image_urls_from_messages(messages: List[Dict[str, Any]]) -> List[str]:
    """
    Scan __messages__ for image_url content blocks, newest message first.
    OWUI multimodal structure:
      { "role": "user", "content": [
          { "type": "text",      "text": "..." },
          { "type": "image_url", "image_url": { "url": "data:image/png;base64,..." } }
      ]}
    """
    found: List[str] = []
    for msg in reversed(messages):
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    iu = part.get("image_url") or {}
                    url = iu.get("url") or iu.get("src") or ""
                    if url:
                        found.append(url)
    return found


# ═══════════════════════════════════════════════════════════════════════════════
#  Video player HTML
# ═══════════════════════════════════════════════════════════════════════════════


def generate_video_player_embed(
    file_path: str, fallback_url: str, prompt: str, mode: str
) -> str:
    pid = uuid.uuid4().hex[:8]
    safe_prompt = (
        prompt.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    mode_label = "🖼️ Image-to-Video" if mode == "I2V" else "✍️ Text-to-Video"
    path_json = json.dumps(file_path)
    fallback_json = json.dumps(fallback_url)
    return f"""<div style="display:flex;justify-content:center;width:100%;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;">
<div style="position:relative;overflow:hidden;border-radius:18px;max-width:640px;width:100%;
  background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);
  box-shadow:0 24px 64px rgba(0,0,0,0.55),0 0 0 1px rgba(255,255,255,0.08);
  color:#fff;box-sizing:border-box;margin-bottom:18px;">
  <div style="padding:14px 18px 10px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,0.08);">
    <div style="display:flex;align-items:center;gap:10px;">
      <div style="width:8px;height:8px;border-radius:50%;background:#e94560;box-shadow:0 0 8px #e94560;"></div>
      <span style="font-size:10px;font-weight:800;letter-spacing:2px;text-transform:uppercase;opacity:0.6;">LTX-Video 2.3</span>
    </div>
    <span style="font-size:10px;font-weight:700;opacity:0.5;background:rgba(255,255,255,0.08);padding:3px 10px;border-radius:999px;">{mode_label}</span>
  </div>
  <div style="position:relative;background:#000;display:flex;align-items:center;justify-content:center;min-height:180px;">
    <div id="sp_{pid}" style="position:absolute;inset:0;z-index:5;display:flex;flex-direction:column;align-items:center;justify-content:center;background:rgba(0,0,0,0.75);gap:12px;pointer-events:none;">
      <div style="width:40px;height:40px;border-radius:50%;border:3px solid rgba(255,255,255,0.15);border-top-color:#e94560;animation:sp_spin_{pid} .85s linear infinite;"></div>
      <span id="sp_label_{pid}" style="font-size:11px;font-weight:700;letter-spacing:1px;opacity:0.65;">Preparing video…</span>
    </div>
    <video id="v_{pid}" controls loop style="width:100%;display:block;max-height:420px;background:#000;opacity:0;transition:opacity .4s;">Your browser does not support the video tag.</video>
  </div>
  <div style="padding:12px 18px 10px;">
    <div style="font-size:8px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;opacity:0.4;margin-bottom:5px;">Prompt</div>
    <div style="font-size:12px;line-height:1.6;opacity:0.78;max-height:72px;overflow-y:auto;word-wrap:break-word;white-space:pre-wrap;">{safe_prompt}</div>
  </div>
  <div style="padding:0 18px 18px;display:flex;gap:10px;">
    <a id="ot_{pid}" href="#" target="_blank" rel="noopener" style="display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,0.12);padding:8px 16px;border-radius:999px;font-size:11px;font-weight:700;color:#fff;text-decoration:none;cursor:pointer;">
      <svg viewBox="0 0 24 24" style="width:11px;height:11px;fill:#fff;flex-shrink:0;"><path d="M19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/></svg>Open
    </a>
    <button id="dl_{pid}" style="display:inline-flex;align-items:center;gap:6px;background:rgba(233,69,96,0.85);border:none;padding:8px 18px;border-radius:999px;font-size:11px;font-weight:800;color:#fff;cursor:pointer;">
      <svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:#fff;flex-shrink:0;"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>Download
    </button>
  </div>
</div></div>
<style>@keyframes sp_spin_{pid} {{ to {{ transform:rotate(360deg); }} }}</style>
<script>
(function(){{
  var filePath={path_json},fallbackUrl={fallback_json};
  var vid=document.getElementById('v_{pid}'),sp=document.getElementById('sp_{pid}');
  var spLabel=document.getElementById('sp_label_{pid}'),dl=document.getElementById('dl_{pid}'),ot=document.getElementById('ot_{pid}');
  var blobUrl=null;
  function authFetch(u){{var o={{credentials:'include'}};try{{var t=localStorage.getItem('token');if(t)o.headers={{'Authorization':'Bearer '+t}};}}catch(e){{}}return fetch(u,o);}}
  function showVideo(){{sp.style.display='none';vid.style.opacity='1';}}
  var safetyTimer=setTimeout(showVideo,12000);
  function loadVideo(p,fb){{
    if(!p){{ot.href=fb;vid.src=fb;vid.addEventListener('loadedmetadata',function(){{clearTimeout(safetyTimer);showVideo();}},{{once:true}});return;}}
    var origin='';try{{origin=window.top.location.origin;}}catch(e){{}}
    var abs=origin?origin+p:p;ot.href=abs;spLabel.textContent='Downloading video…';
    authFetch(abs).then(function(r){{if(!r.ok)throw new Error('HTTP '+r.status);return r.blob();}}).then(function(b){{
      if(blobUrl)URL.revokeObjectURL(blobUrl);blobUrl=URL.createObjectURL(b);vid.src=blobUrl;
      vid.addEventListener('loadedmetadata',function(){{clearTimeout(safetyTimer);showVideo();}},{{once:true}});
    }}).catch(function(e){{
      console.warn('authFetch failed:',e);vid.src=abs;
      vid.addEventListener('loadedmetadata',function(){{clearTimeout(safetyTimer);showVideo();}},{{once:true}});
      setTimeout(function(){{if(vid.readyState<1){{ot.href=fb;vid.src=fb;}}}},5000);
    }});
  }}
  dl.addEventListener('click',function(){{
    var origin='';try{{origin=window.top.location.origin;}}catch(e){{}}
    var t=filePath?(origin?origin+filePath:filePath):fallbackUrl;
    if(t.indexOf('/api/')===-1){{window.open(t,'_blank','noopener');return;}}
    authFetch(t).then(function(r){{if(!r.ok)throw new Error('HTTP '+r.status);return r.blob();}}).then(function(b){{
      var u=URL.createObjectURL(b),a=document.createElement('a');
      a.href=u;a.download='ltx_video.mp4';document.body.appendChild(a);a.click();document.body.removeChild(a);URL.revokeObjectURL(u);
    }}).catch(function(){{window.open(t,'_blank','noopener');}});
  }});
  loadVideo(filePath,fallbackUrl);
}})();
</script>"""


# ═══════════════════════════════════════════════════════════════════════════════
#  Shared infra helpers
# ═══════════════════════════════════════════════════════════════════════════════


async def _get_ollama_models(api_url: str) -> List[Dict[str, Any]]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{api_url.rstrip('/')}/api/ps") as r:
                return (
                    cast(List[Dict[str, Any]], (await r.json()).get("models", []))
                    if r.status == 200
                    else []
                )
    except Exception as e:
        logger.debug("Ollama /api/ps error: %s", e)
        return []


async def _unload_ollama_models(api_url: str) -> bool:
    loaded = await _get_ollama_models(api_url)
    if not loaded:
        return True
    try:
        async with aiohttp.ClientSession() as s:
            for m in loaded:
                name = m.get("name") or m.get("model", "")
                if name:
                    await s.post(
                        f"{api_url.rstrip('/')}/api/generate",
                        json={"model": name, "keep_alive": 0},
                    )
    except Exception as e:
        logger.warning("Ollama unload error: %s", e)
    for _ in range(10):
        await asyncio.sleep(1)
        if not await _get_ollama_models(api_url):
            return True
    return False


async def _unload_llamacpp_models(api_url: str) -> bool:
    """
    Unload all loaded models from a llama.cpp router instance.
    Mirrors the logic in the VRAM Unload action tool.
    Returns True if all models were unloaded (or none were loaded), False on error.
    """
    base = api_url.rstrip("/")
    loaded: List[str] = []
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{base}/v1/models", timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status != 200:
                    logger.warning("llama.cpp /v1/models returned HTTP %d", r.status)
                    return False
                data = await r.json()
                for m in data.get("data", []):
                    status = m.get("status", {})
                    status_val = (
                        status.get("value", "") if isinstance(status, dict) else status
                    )
                    if status_val == "loaded":
                        loaded.append(m["id"])
    except Exception as e:
        logger.warning("llama.cpp /v1/models error: %s", e)
        return False

    if not loaded:
        logger.info("llama.cpp: no models currently loaded.")
        return True

    failed = 0
    async with aiohttp.ClientSession() as s:
        for model_id in loaded:
            try:
                async with s.post(
                    f"{base}/models/unload",
                    json={"model": model_id},
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as r:
                    if r.status in (200, 204):
                        logger.info("llama.cpp: unloaded model '%s'", model_id)
                    else:
                        failed += 1
                        logger.warning(
                            "llama.cpp: failed to unload '%s' — HTTP %d",
                            model_id,
                            r.status,
                        )
            except Exception as e:
                failed += 1
                logger.warning("llama.cpp: error unloading '%s': %s", model_id, e)

    return failed == 0


async def _upload_image_to_comfyui(
    http_url: str,
    image_bytes: bytes,
    filename: str,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    form = aiohttp.FormData()
    form.add_field(
        "image", io.BytesIO(image_bytes), filename=filename, content_type="image/png"
    )
    form.add_field("type", "input")
    form.add_field("overwrite", "true")
    async with aiohttp.ClientSession(headers=headers) as s:
        async with s.post(f"{http_url.rstrip('/')}/upload/image", data=form) as resp:
            resp.raise_for_status()
            stored = (await resp.json()).get("name", filename)
            logger.info("Image uploaded to ComfyUI as: %s", stored)
            return stored


async def _submit_and_wait(
    ws_url: str,
    http_url: str,
    payload: Dict[str, Any],
    client_id: str,
    max_wait: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    start = asyncio.get_event_loop().time()
    prompt_id: Optional[str] = None
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.ws_connect(f"{ws_url}?clientId={client_id}") as ws:
                async with session.post(f"{http_url}/prompt", json=payload) as resp:
                    if resp.status != 200:
                        raise Exception(
                            f"Queue failed: {resp.status} – {await resp.text()}"
                        )
                    rj = await resp.json()
                    prompt_id = rj.get("prompt_id")
                    if not prompt_id:
                        raise Exception("No prompt_id from ComfyUI")
                last_poll = 0.0
                while True:
                    if asyncio.get_event_loop().time() - start > max_wait:
                        raise TimeoutError(f"Timed out after {max_wait}s")
                    now = asyncio.get_event_loop().time()
                    if now - last_poll > 3.0:
                        last_poll = now
                        try:
                            async with session.get(
                                f"{http_url}/history/{prompt_id}"
                            ) as hr:
                                if hr.status == 200:
                                    h = await hr.json()
                                    if prompt_id in h:
                                        return h[prompt_id]
                        except Exception:
                            pass
                    try:
                        msg = await ws.receive(timeout=1.0)
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            m = json.loads(msg.data)
                            t, d = m.get("type", ""), m.get("data", {})
                            if (
                                t in ("execution_cached", "executed")
                                and d.get("prompt_id") == prompt_id
                            ):
                                async with session.get(
                                    f"{http_url}/history/{prompt_id}"
                                ) as fr:
                                    if fr.status == 200:
                                        h = await fr.json()
                                        if prompt_id in h:
                                            return h[prompt_id]
                            elif (
                                t == "execution_error"
                                and d.get("prompt_id") == prompt_id
                            ):
                                raise Exception(
                                    f"ComfyUI error on node {d.get('node_id','?')}: {d.get('exception_message','unknown')}"
                                )
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        logger.warning("WS error: %s – polling", e)
                        break
        except Exception as e:
            if not prompt_id:
                raise
            logger.warning("WS failed (%s) – polling", e)
        if prompt_id:
            while asyncio.get_event_loop().time() - start <= max_wait:
                await asyncio.sleep(2)
                try:
                    async with session.get(f"{http_url}/history/{prompt_id}") as hr:
                        if hr.status == 200:
                            h = await hr.json()
                            if prompt_id in h:
                                return h[prompt_id]
                except Exception:
                    pass
            raise TimeoutError(f"Polling timed out after {max_wait}s")
    raise Exception("Generation flow failed to start.")


def _extract_videos(job: Dict[str, Any]) -> List[Dict[str, str]]:
    candidates: List[Tuple[str, str]] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, str) and any(obj.lower().endswith(e) for e in VIDEO_EXTS):
            candidates.append((obj, ""))
        elif isinstance(obj, dict):
            fname = None
            for k in ("filename", "file", "path", "name"):
                v = obj.get(k)
                if isinstance(v, str) and any(
                    v.lower().endswith(e) for e in VIDEO_EXTS
                ):
                    fname = v
                    break
            if fname:
                sub = ""
                for sk in ("subfolder", "subdir", "folder", "directory"):
                    sv = obj.get(sk)
                    if isinstance(sv, str):
                        sub = sv.strip("/ ")
                        break
                candidates.append((fname, sub))
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(job)
    seen: set = set()
    result: List[Dict[str, str]] = []
    for fn, sub in candidates:
        fn = os.path.basename(fn)
        key = f"{sub}/{fn}" if sub else fn
        if key not in seen:
            seen.add(key)
            result.append({"filename": fn, "subfolder": sub})
    return result


def _reencode_for_mobile(video_bytes: bytes) -> bytes:
    """Re-encode to H.264 yuv420p + faststart — required for iOS/WhatsApp sharing."""
    import subprocess, tempfile, os as _os

    in_path = out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(video_bytes)
            in_path = tmp.name
        out_path = in_path + "_mobile.mp4"
        r = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                in_path,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                out_path,
            ],
            capture_output=True,
            timeout=120,
        )
        if r.returncode == 0:
            data = open(out_path, "rb").read()
            logger.info("ffmpeg re-encode OK → %d bytes", len(data))
            return data
        logger.warning("ffmpeg re-encode failed:\n%s", r.stderr.decode())
    except Exception as e:
        logger.warning("ffmpeg re-encode error: %s", e)
    finally:
        for p in (in_path, out_path):
            if p:
                try:
                    _os.unlink(p)
                except:
                    pass
    return video_bytes


async def _store_video(
    http_url: str,
    filename: str,
    subfolder: str,
    request: Any,
    user: Any,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    sub_param = f"&subfolder={quote(subfolder)}" if subfolder else ""
    fallback_url = (
        f"{http_url}/api/viewvideo?filename={quote(filename)}&type=output{sub_param}"
    )
    try:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.get(fallback_url) as resp:
                resp.raise_for_status()
                content = await resp.read()
        content = _reencode_for_mobile(content)
        if request and user:
            upload = UploadFile(file=io.BytesIO(content), filename=filename)
            item = upload_file_handler(
                request=request, file=upload, metadata={}, process=False, user=user
            )
            fid = getattr(item, "id", None)
            if fid:
                return f"/api/v1/files/{fid}/content", fallback_url
    except Exception as e:
        logger.debug("Could not store video in OWUI: %s", e)
    return "", fallback_url


# ═══════════════════════════════════════════════════════════════════════════════
#  Shared generation core
# ═══════════════════════════════════════════════════════════════════════════════


async def _run_generation(
    *,
    mode: str,
    prompt: str,
    valves: "Tools.Valves",
    image_bytes: Optional[bytes],
    image_filename: Optional[str],
    video_title: str,
    emit: Callable[[str, bool], Awaitable[None]],
    request: Any,
    user: Any,
    event_emitter: Optional[Callable[[Any], Awaitable[None]]],
) -> str:
    import copy

    http_url = valves.comfyui_api_url.rstrip("/")
    ws_url = http_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
    auth_headers: Dict[str, str] = {}
    if valves.comfyui_api_key:
        auth_headers["Authorization"] = f"Bearer {valves.comfyui_api_key}"

    if valves.unload_ollama_models:
        await emit("⏳ Unloading Ollama models from VRAM…", False)
        if not await _unload_ollama_models(valves.ollama_api_url):
            logger.warning("Ollama unload may be incomplete.")
        await asyncio.sleep(1)

    if valves.unload_llamacpp_models:
        await emit("⏳ Unloading llama.cpp models from VRAM…", False)
        if not await _unload_llamacpp_models(valves.llamacpp_api_url):
            logger.warning("llama.cpp unload may be incomplete.")
        await asyncio.sleep(1)

    workflow = copy.deepcopy(I2V_WORKFLOW if mode == "I2V" else T2V_WORKFLOW)
    _slug = (
        re.sub(r"[^a-zA-Z0-9]+", "_", video_title.strip())[:40].strip("_") or "Video"
    )
    _mode_tag = "i2v" if mode == "I2V" else "t2v"
    workflow["75"]["inputs"]["filename_prefix"] = f"video/{_slug}_{_mode_tag}"
    workflow["267:266"]["inputs"]["value"] = prompt
    workflow["267:216"]["inputs"]["noise_seed"] = random.randint(1, 2**31 - 1)
    workflow["267:237"]["inputs"]["noise_seed"] = random.randint(1, 2**31 - 1)
    if mode == "T2V":
        workflow["267:257"]["inputs"]["value"] = valves.t2v_width
        workflow["267:258"]["inputs"]["value"] = valves.t2v_height
    workflow["267:225"]["inputs"]["value"] = valves.video_length_frames
    workflow["267:260"]["inputs"]["value"] = valves.frame_rate

    if mode == "I2V":
        if not image_bytes:
            return "❌ I2V mode requires image bytes but none were resolved."
        await emit("⬆️ Uploading reference image to ComfyUI…", False)
        stored_name = await _upload_image_to_comfyui(
            http_url, image_bytes, image_filename or "upload.png", headers=auth_headers
        )
        workflow["269"]["inputs"]["image"] = stored_name

    mode_label = "🖼️ Image-to-Video" if mode == "I2V" else "✍️ Text-to-Video"
    await emit(f"🎬 Submitting {mode_label} job to ComfyUI…", False)
    client_id = str(uuid.uuid4())
    await emit("⏳ Generating video – this may take a few minutes…", False)
    job_result = await _submit_and_wait(
        ws_url,
        http_url,
        {"prompt": workflow, "client_id": client_id},
        client_id,
        valves.max_wait_time,
        headers=auth_headers,
    )

    videos = _extract_videos(job_result)
    if not videos:
        logger.warning("No video in job output: %s", json.dumps(job_result, indent=2))
        return "⚠️ ComfyUI job finished but no video output was found."

    current_user = Users.get_user_by_id(user["id"]) if user else None
    file_path, fallback_url = await _store_video(
        http_url,
        videos[0]["filename"],
        videos[0]["subfolder"],
        request,
        current_user,
        headers=auth_headers,
    )
    await emit("✅ Video ready!", True)

    player_html = generate_video_player_embed(file_path, fallback_url, prompt, mode)
    if event_emitter:
        await event_emitter({"type": "embeds", "data": {"embeds": [player_html]}})
    return "The video has been generated and the player is embedded above. The user can watch it in chat or download it."


# ═══════════════════════════════════════════════════════════════════════════════
#  Tool class — two public methods exposed to the LLM
# ═══════════════════════════════════════════════════════════════════════════════


class Tools:
    class Valves(BaseModel):
        comfyui_api_url: str = Field(
            default="http://localhost:8188", description="ComfyUI HTTP API endpoint."
        )
        comfyui_api_key: str = Field(
            default="",
            description="Bearer token for ComfyUI (leave empty if not required).",
            json_schema_extra={"input": {"type": "password"}},
        )
        owui_internal_base: str = Field(
            default="http://localhost:8080",
            description="Internal URL the tool uses server-side to fetch OWUI files. Usually http://localhost:<port>.",
        )
        video_length_frames: int = Field(
            default=121, description="Number of frames (121 ≈ 5 s at 24 fps)."
        )
        frame_rate: int = Field(default=24, description="Output frame-rate (fps).")
        t2v_width: int = Field(
            default=1280, description="Width for Text-to-Video (px)."
        )
        t2v_height: int = Field(
            default=720, description="Height for Text-to-Video (px)."
        )
        max_wait_time: int = Field(
            default=600, description="Max seconds to wait for ComfyUI."
        )
        unload_ollama_models: bool = Field(
            default=True,
            description="Unload Ollama models from VRAM before generating.",
        )
        ollama_api_url: str = Field(
            default="http://localhost:11434", description="Ollama API URL."
        )
        unload_llamacpp_models: bool = Field(
            default=False,
            description="Unload llama.cpp router models from VRAM before generating.",
        )
        llamacpp_api_url: str = Field(
            default="http://localhost:8082",
            description="llama.cpp router base URL (used when unload_llamacpp_models is enabled).",
        )

    class UserValves(BaseModel):
        video_duration: Literal["5s", "10s", "15s", "20s", "25s", "30s"] = Field(
            default="10s",
            description="Video length at 24 fps: 5 s (121), 10 s (241), 15 s (361), 20 s (481), 25 s (601), 30 s (721 frames).",
        )
        frame_rate: int = Field(
            default=24,
            description="Output frame-rate (fps).",
        )
        t2v_width: int = Field(
            default=1280,
            description="Width for Text-to-Video output (px).",
        )
        t2v_height: int = Field(
            default=720,
            description="Height for Text-to-Video output (px).",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.user_valves = self.UserValves()

    # ── Tool 1: Text-to-Video ──────────────────────────────────────────────

    async def generate_video_t2v(
        self,
        prompt: str,
        video_title: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
        __user__: Optional[Dict[str, Any]] = None,
        __request__: Optional[Any] = None,
    ) -> str:
        """
        Generate a video purely from a text prompt (Text-to-Video).

        video_title: A short creative 2-4 word title for this video (e.g. "Pikachu Forest Sprint").
          Used as the output filename. Make it evocative and unique — NOT a truncation of the prompt.
        Call this when the user has NOT uploaded an image.
        Output resolution: 1280x720. Seeds are randomised automatically.
        """

        import copy

        # Merge per-user overrides on top of admin valves
        _uv = (__user__ or {}).get("valves") or self.UserValves()
        _duration_frames = {
            "5s": 121,
            "10s": 241,
            "15s": 361,
            "20s": 481,
            "25s": 601,
            "30s": 721,
        }
        effective_valves = copy.copy(self.valves)
        effective_valves.video_length_frames = _duration_frames.get(
            getattr(_uv, "video_duration", "10s"), 241  # default 10s
        )
        effective_valves.frame_rate = _uv.frame_rate
        effective_valves.t2v_width = _uv.t2v_width
        effective_valves.t2v_height = _uv.t2v_height

        async def _emit(desc: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": desc, "done": done}}
                )

        global OWUI_INTERNAL_BASE
        if self.valves.owui_internal_base:
            OWUI_INTERNAL_BASE = self.valves.owui_internal_base
        try:
            return await _run_generation(
                mode="T2V",
                prompt=prompt,
                valves=effective_valves,
                image_bytes=None,
                image_filename=None,
                video_title=video_title,
                emit=_emit,
                request=__request__,
                user=__user__,
                event_emitter=__event_emitter__,
            )
        except TimeoutError as e:
            msg = f"⏱️ Generation timed out: {e}"
            await _emit(msg, True)
            return msg
        except Exception as e:
            logger.error("T2V error: %s", e, exc_info=True)
            msg = f"❌ Error: {e}"
            await _emit(msg, True)
            return msg

    # ── Tool 2: Image-to-Video ─────────────────────────────────────────────

    async def generate_video_i2v(
        self,
        prompt: str,
        video_title: str,
        image_url: str,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
        __user__: Optional[Dict[str, Any]] = None,
        __request__: Optional[Any] = None,
        __messages__: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Animate an uploaded image into a video (Image-to-Video).

        video_title: A short creative 2-4 word title for this video (e.g. "Dragon Awakens Dawn").
          Used as the output filename. Make it evocative and unique — NOT a truncation of the prompt.
        Call this when the user HAS uploaded an image and wants it animated.

        image_url parameter (REQUIRED):
          You MUST pass the full image URL exactly as it appears in the
          conversation message content. It will be one of:
            • "data:image/png;base64,<very long base64 string>"
            • "/api/v1/files/<uuid>/content"
          Extract this from the image_url.url field of the image_url content
          block in the user's message. Do NOT paraphrase, shorten, or omit it.

        Output resolution automatically matches the input image.
        Seeds are randomised automatically.
        """

        import copy

        # Merge per-user overrides on top of admin valves
        _uv = (__user__ or {}).get("valves") or self.UserValves()
        _duration_frames = {
            "5s": 121,
            "10s": 241,
            "15s": 361,
            "20s": 481,
            "25s": 601,
            "30s": 721,
        }
        effective_valves = copy.copy(self.valves)
        effective_valves.video_length_frames = _duration_frames.get(
            getattr(_uv, "video_duration", "10s"), 241  # default 10s
        )
        effective_valves.frame_rate = _uv.frame_rate
        effective_valves.t2v_width = _uv.t2v_width
        effective_valves.t2v_height = _uv.t2v_height

        async def _emit(desc: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": desc, "done": done}}
                )

        global OWUI_INTERNAL_BASE
        if self.valves.owui_internal_base:
            OWUI_INTERNAL_BASE = self.valves.owui_internal_base
        owui_base = self.valves.owui_internal_base or OWUI_INTERNAL_BASE

        # ── Resolve image bytes ────────────────────────────────────────────
        image_bytes: Optional[bytes] = None

        # Strategy 1: LLM-supplied image_url argument
        if image_url and image_url.strip():
            logger.info("I2V: trying image_url arg (%.80s…)", image_url)
            image_bytes = await _bytes_from_url(image_url.strip(), owui_base)

        # Strategy 2: scan __messages__ for any image_url content blocks
        if image_bytes is None and __messages__:
            logger.info(
                "I2V: scanning __messages__ for image URLs (%d messages)",
                len(__messages__),
            )
            for url in _extract_image_urls_from_messages(__messages__):
                logger.info("I2V: trying message URL (%.80s…)", url)
                image_bytes = await _bytes_from_url(url, owui_base)
                if image_bytes:
                    break

        if image_bytes is None:
            return (
                "❌ Could not load the image for Image-to-Video. "
                "Please ensure an image is uploaded in this conversation. "
                f"(image_url received: {(image_url or 'none')[:120]})"
            )

        logger.info("I2V: image resolved — %d bytes", len(image_bytes))

        try:
            return await _run_generation(
                mode="I2V",
                prompt=prompt,
                valves=effective_valves,
                image_bytes=image_bytes,
                image_filename="input_image.png",
                video_title=video_title,
                emit=_emit,
                request=__request__,
                user=__user__,
                event_emitter=__event_emitter__,
            )
        except TimeoutError as e:
            msg = f"⏱️ Generation timed out: {e}"
            await _emit(msg, True)
            return msg
        except Exception as e:
            logger.error("I2V error: %s", e, exc_info=True)
            msg = f"❌ Error: {e}"
            await _emit(msg, True)
            return msg
