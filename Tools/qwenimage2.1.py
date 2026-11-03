"""
title: Qwen Image 2.1
author: ichrist
version: 1.0.0
license: MIT
requirements: aiohttp
description: Generate (text2image) / edit / composite images with Qwen Image 2.1 via ComfyUI
"""

import asyncio
import base64
import copy
import hashlib
import io
import json
import logging
import os
import random
import re
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

import aiohttp
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_IMAGES = 10

# ─── Node IDs in the exported API workflow ─────────────────────────────────────
# (change these if you re-export the workflow and the IDs differ)
N_ENCODE = "459:474"  # TextEncodeQwenImage21 (images.image_1 .. images.image_10)
N_KSAMPLER = "459:458"
N_PROMPT_SWITCH = "459:484"  # If/Else switch feeding PreviewAny -> encode prompt
N_ENH_BATCH = "459:485"  # BatchImagesNode (images for the prompt enhancer)
N_ENH_GEN = "459:500"  # TextGenerate (prompt enhancer)
N_ENH_ALL = ["459:477", "459:479", "459:485", "459:500"]  # enhancer-only nodes
N_OLD_LOADERS = ["470", "513"]  # LoadImage nodes in the export (replaced)
LOADER_PREFIX = "img_in_"

# ─── T2I workflow node IDs ─────────────────────────────────────────────────────
T2I_KSAMPLER = "459:458"
T2I_LATENT = "459:456"  # EmptyLatentImage (width/height set from aspect ratio)
T2I_PROMPT_SWITCH = "459:474"  # If/Else switch feeding PreviewAny -> encode prompt
T2I_ENH_GEN = "459:471"  # TextGenerate (prompt enhancer)
T2I_ENH_ALL = ["459:471", "459:473", "459:475"]  # enhancer-only nodes

# Embedded workflow (your API export, minus the two fixed LoadImage nodes).
EMBEDDED_WORKFLOW = json.loads(
    '{"461": {"inputs": {"filename_prefix": "Qwen_image_2.1", "format": "png", "format.bit_depth": "8-bit", "format.input_color_space": "sRGB", "images": ["511", 0]}, "class_type": "SaveImageAdvanced", "_meta": {"title": "Save Image (Advanced)"}}, "510": {"inputs": {"value": ["459:457", 0]}, "class_type": "UnloadAllModels", "_meta": {"title": "UnloadAllModels"}}, "511": {"inputs": {"anything": ["512", 0]}, "class_type": "easy clearCacheAll", "_meta": {"title": "Clear Cache All"}}, "512": {"inputs": {"anything": ["510", 0]}, "class_type": "easy cleanGpuUsed", "_meta": {"title": "Clean VRAM Used"}}, "459:451": {"inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}, "class_type": "UNETLoader", "_meta": {"title": "Load Diffusion Model"}}, "459:453": {"inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}, "class_type": "CLIPLoader", "_meta": {"title": "Load CLIP"}}, "459:454": {"inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}, "class_type": "VAELoader", "_meta": {"title": "Load VAE"}}, "459:456": {"inputs": {"width": 1024, "height": 1024, "batch_size": 1}, "class_type": "EmptyLatentImage", "_meta": {"title": "Empty Latent Image"}}, "459:457": {"inputs": {"samples": ["459:458", 0], "vae": ["459:454", 0]}, "class_type": "VAEDecode", "_meta": {"title": "VAE Decode"}}, "459:458": {"inputs": {"seed": 891836227295375, "steps": 25, "cfg": 1, "sampler_name": "euler", "scheduler": "beta", "denoise": 1, "model": ["459:469", 0], "positive": ["459:474", 0], "negative": ["459:474", 1], "latent_image": ["459:468", 0]}, "class_type": "KSampler", "_meta": {"title": "KSampler"}}, "459:468": {"inputs": {"switch": false, "on_false": ["459:474", 2], "on_true": ["459:456", 0]}, "class_type": "ComfySwitchNode", "_meta": {"title": "If/Else Switch"}}, "459:469": {"inputs": {"device": "auto", "dtype": "default", "model": ["459:451", 0]}, "class_type": "QwenImage21Cache", "_meta": {"title": "Qwen Image 2.1 Cache"}}, "459:474": {"inputs": {"prompt": ["459:480", 0], "negative_prompt": "", "resolution": 0, "clip": ["459:453", 0], "images.image_1": ["470", 0], "vae": ["459:454", 0], "images.image_3": ["513", 0]}, "class_type": "TextEncodeQwenImage21", "_meta": {"title": "Text Encode Qwen Image 2.1"}}, "459:477": {"inputs": {"clip_name": "qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors", "type": "qwen_image", "device": "default"}, "class_type": "CLIPLoader", "_meta": {"title": "Load CLIP"}}, "459:479": {"inputs": {"value": "# Edit Prompt Enhancer — General (v2, 精简版)\\n\\n**FIRST — there are TWO separate language decisions. Do NOT conflate them.**\\n\\n**(A) Language of the rewritten prompt\'s DESCRIPTIVE prose — every word OUTSIDE double quotes (the description you write for the diffusion model, NOT the text painted into the image). This decision is final and non-negotiable:**\\n- User instruction is in Chinese → write the description in Chinese.\\n- User instruction is in English → write the description in English.\\n- User instruction is in ANY other language (Japanese, Korean, French, Spanish, Thai, etc.) → write the description in English.\\n\\n**(B) Language of the TEXT THAT WILL BE RENDERED INTO THE OUTPUT IMAGE — the content INSIDE double quotes. Decide it in this strict priority order:**\\n1. If the user\'s instruction gives the exact text to write, OR names a target language for the text (e.g. \\"改成\'夏日特惠\'\\", \\"把标题写成英文\\", \\"add a Japanese title\\", \\"write the caption in Thai\\") → render exactly that text / in exactly that specified language.\\n2. Otherwise, if the input image already contains text → render in the DOMINANT language of the image\'s existing text — even when the instruction is written in a different language.\\n3. Otherwise (the image contains no text AND the instruction names no target language) → render in the language of the user\'s instruction itself — including Japanese, Korean, Thai, Arabic, French, etc. Do NOT force it to English.\\nWorked example: image is mostly Thai, instruction is in English asking to add/redesign a title without giving the exact words or a language → the rendered (quoted) text must be **Thai** (the image\'s dominant language), while the surrounding description (A) is still written in English.\\n\\nTwo reinforcements on decision (B): all rendered (quoted) text must be **monolingual** — do not mix Chinese and English inside the quotes and do not emit a bilingual pair unless the user explicitly asks for one. And **genre never overrides input language**: a \\"spec sheet / cinematic data-document / storyboard / technical parameter\\" look is achieved through layout and typography, NOT by switching rendered labels to English — every header, label, and caption stays in the decided language (standardized units and user-given proper nouns may remain Latin).\\n\\nYou are an expert at clarifying image editing instructions. Given a user\'s vague or ambiguous edit instruction and the input image(s), rewrite it into a precise, unambiguous, actionable editing directive. An input image is ALWAYS present — this is always an image-editing task, never text-to-image from nothing.\\n\\n## Core Objective\\n\\nRewrite the instruction so a downstream image-editing model can execute it without guessing — anchored on what the input image(s) actually show, faithful to the user\'s intent, inventing nothing.\\n\\n**How much you build is intent-branched.** When the user wants *this picture changed* (a local object/attribute/background edit, a text or UI edit, a quality or style change, a viewpoint/canvas transform), clarify and constrain: say exactly what changes, and let everything else stand. When the user wants *a new picture of this subject* (placing a subject in a new scene, compositing across images, a photo-shoot or poster or infographic built from a reference), construct actively: design the scene, lighting, composition and layout to a professional standard. Scale the elaboration to what was asked — a plain placement stays restrained, a styled shoot or a publication-grade poster is built out fully.\\n\\n## The Governing Principle — Attribute Disentanglement at Full Strength\\n\\n**Edit exactly the attribute(s) the user named, push each to a strong and unmistakable degree, and hold everything else at input fidelity.**\\n\\nBoth halves matter, and the two failure modes are symmetric:\\n\\n- **Leakage** — touching what the user did not name (a sharpen that re-grades color, an upscale that reframes, a style change that drifts a face, an outfit swap that drops an accessory, a background change that \\"helpfully\\" cleans up something unmentioned).\\n- **Under-editing** — an output a viewer could mistake for the unedited input, because the requested change was applied faintly.\\n\\nPreservation locks **content, never edit strength**. Recognizability is bought by naming what stays fixed, not by holding the effect back.\\n\\n## What to Anchor, What to Decide\\n\\n**Anchor on the image.** Every spatial, tonal and contextual claim comes from what is visibly there. If you are unsure a detail exists, leave it out — a preserved element described at a higher level of abstraction is always safer than an invented specific.\\n\\n**Say what stays, without repainting it.** Name the untargeted content by type, position and role rather than describing its appearance, and prefer one blanket preservation clause over walking the frame. A preservation description reads to the model as a generation instruction: the more concretely you describe something you meant to keep, the more likely it drifts. Describe appearance concretely only for what you are actually changing, or when it is the only way to disambiguate between similar objects.\\n\\n**Identity is the hardest invariant.** A person\'s facial identity and the personal accessories that make them recognizable; a product\'s exact design, markings and count; and the input\'s rendering medium (photograph, anime, illustration, sketch, 3D render, painting) all survive every edit unless the user explicitly targets them. When identity comes from a reference image, point at that image rather than describing features in words — verbal descriptions make the model regenerate and degrade the likeness.\\n\\n**Resolve ambiguity, then commit.** Turn vague intent, imprecise spatial reference and unparameterized style words into something concrete and observable. Translate abstract quality language into the visual properties it implies. Where the instruction offers alternatives or contradicts itself, pick the most reasonable reading and state it as a decision. Keep the user\'s own action verb, spatial relations and described state intact, and treat anything they asked to preserve as absolute. Preserve creative or physically impossible intent rather than correcting it.\\n\\n**Only what was asked.** Do not add operations the user did not request, and do not clean up unmentioned defects, overlays or clutter however prominent they look. When an edit removes, moves or reveals something, say enough about the newly exposed region that the result stays physically coherent.\\n\\n**Text in the image is literal.** Whenever readable text will appear in the output, commit to the exact characters — every element, quoted, nothing summarized or abbreviated away. Text you cannot commit to should not be added at all. Match the typography and language the input establishes unless the user asks otherwise. When the operation extends the canvas outward, name it as outpainting explicitly.\\n\\n**Write it as an instruction.** Lead with the operation, not a description of the finished picture, and write from the perspective of someone holding only the input image(s).\\n\\n## Thinking Process\\n\\nBefore emitting the final prompt, reason through: what the image(s) actually contain (including a complete reading of any text present); what the user is asking for and which attributes that names; what must therefore stay fixed; and finally the composed directive. Close with a check that every visible element is either the target of the edit or covered by what stays fixed, that the requested change is unmistakable, that nothing outside the target was touched, and that every quoted string obeys language decision (B).\\n\\n## Image Reference Rules\\n\\nFor Multi-Image Input (N >= 2), the rewritten instruction MUST use `<image1>`, `<image2>`, ... to refer to each input image. Do not use natural language references like \\"图1\\", \\"第一张图\\", \\"the first image\\", or \\"image A\\". This tagging format is mandatory and non-negotiable. For single-image input (N = 1), do NOT use tags — refer to the image naturally (\\"图像\\", \\"图片中\\", \\"the image\\").\\n\\nState each image\'s role explicitly — which one is the canvas whose composition and untargeted content survive, and which supply material to transfer — and say what is taken from each. For scene generation with no canvas (合影/合照 and the like), all images serve as identity sources. Describe every referenced image individually; never compress several into a range or a group to avoid describing them one by one.\\n\\n## Output Format\\nOutput ONLY the rewritten editing instruction itself: one single continuous paragraph of plain text.\\n\\nFormatting rules:\\n- The entire rewritten prompt must be a single continuous paragraph with NO line breaks or newline characters.\\n- The response must contain nothing except the instruction itself: no object or array wrapper, no field names or key-value pairs, no headings, labels, or prefaces, no greetings, explanations, or commentary, no markdown, and no code fences. Begin with the first word of the instruction and end with its last word.\\n- Do not wrap the whole instruction in quotes: double quotes are reserved for text that will be RENDERED in the image (next rule).\\n- All text that should appear as visible, readable content in the output image must be enclosed in double quotes (\\"\\"). Descriptive or structural language that does not appear as rendered text should NOT be quoted.\\n- **Never include any resolution or aspect ratio information** (e.g., \\"2:3\\", \\"16:9\\", \\"1920x1080\\", \\"2K\\", \\"4K\\"). Output size is decided downstream, not by you.\\n- Write it out in full — no ellipsis, no truncation.\\n- State requirements affirmatively (\\"保持背景与输入图完全一致\\") rather than as prohibitions (\\"禁止改变背景\\"). Standard preservation phrasing \\"保持/保留[X]不变\\" is fine.\\n- Be precise and decisive: no hedging, no unresolved alternatives, no vague degree words left unresolved.\\n- The descriptive prose (outside double quotes) follows language decision (A); the text rendered inside the image (inside double quotes) follows language decision (B). Retain proper nouns and domain-specific terms in their original language, placed in English double quotes.\\n- **Language-purge self-check (do this last)**: re-scan every double-quoted string — the text that will be RENDERED in the image — and enforce language decision (B). No quoted string may mix Chinese and English, form a bilingual pair, or carry a parenthetical translation gloss unless the user explicitly asked. Standardized units and user-given proper nouns may remain Latin.\\n\\nThe user\'s edit instruction to rewrite is:"}, "class_type": "PrimitiveStringMultiline", "_meta": {"title": "Text (System Prompt)"}}, "459:480": {"inputs": {"source": ["459:484", 0]}, "class_type": "PreviewAny", "_meta": {"title": "Preview as Text"}}, "459:484": {"inputs": {"switch": false, "on_false": "Replace costumes for the character", "on_true": ["459:500", 0]}, "class_type": "ComfySwitchNode", "_meta": {"title": "If/Else Switch"}}, "459:485": {"inputs": {"images.image0": ["470", 0], "images.image5": ["513", 0]}, "class_type": "BatchImagesNode", "_meta": {"title": "Batch Images"}}, "459:500": {"inputs": {"prompt": "Replace costumes for the character", "max_length": 4096, "sampling_mode": "on", "sampling_mode.temperature": 1, "sampling_mode.top_k": 20, "sampling_mode.top_p": 0.95, "sampling_mode.min_p": 0, "sampling_mode.repetition_penalty": 1, "sampling_mode.seed": 891836227295375, "sampling_mode.presence_penalty": 0, "thinking": false, "use_default_template": true, "mtp": "auto", "clip": ["459:477", 0], "image": ["459:485", 0], "system_prompt": ["459:479", 0]}, "class_type": "TextGenerate", "_meta": {"title": "Generate Text"}}}'
)


# ─── Workflow patching ─────────────────────────────────────────────────────────


def _load_base_workflow(path: str, inline_json: str) -> Dict[str, Any]:
    """Priority: workflow_json valve > workflow_path file > embedded copy."""
    if inline_json.strip():
        return json.loads(inline_json)
    if path.strip():
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Workflow JSON not found at '{path}'.")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return copy.deepcopy(EMBEDDED_WORKFLOW)


def _build_workflow(
    base: Dict[str, Any],
    comfy_files: List[str],
    prompt: str,
    seed: int,
    use_enhancer: bool,
) -> Dict[str, Any]:
    wf = copy.deepcopy(base)
    n = len(comfy_files)

    # 1. Replace the fixed LoadImage nodes with exactly n loaders
    for nid in N_OLD_LOADERS:
        wf.pop(nid, None)
    loader_ids: List[str] = []
    for i, fname in enumerate(comfy_files):
        nid = f"{LOADER_PREFIX}{i + 1}"
        wf[nid] = {
            "inputs": {"image": fname},
            "class_type": "LoadImage",
            "_meta": {"title": f"Load Image {i + 1}"},
        }
        loader_ids.append(nid)

    # 2. Wire TextEncodeQwenImage21: only image_1..image_n exist
    enc = wf[N_ENCODE]["inputs"]
    for k in [k for k in enc if k.startswith("images.")]:
        del enc[k]
    for i, nid in enumerate(loader_ids):
        enc[f"images.image_{i + 1}"] = [nid, 0]

    # 3. Seed
    wf[N_KSAMPLER]["inputs"]["seed"] = seed

    # 4. Prompt path
    sw = wf[N_PROMPT_SWITCH]["inputs"]
    if use_enhancer:
        batch = wf[N_ENH_BATCH]["inputs"]
        for k in [k for k in batch if k.startswith("images.")]:
            del batch[k]
        for i, nid in enumerate(loader_ids):
            batch[f"images.image{i}"] = [nid, 0]
        gen = wf[N_ENH_GEN]["inputs"]
        gen["prompt"] = prompt
        gen["sampling_mode.seed"] = seed
        sw["switch"] = True
        sw["on_true"] = [N_ENH_GEN, 0]
        sw["on_false"] = prompt
    else:
        for nid in N_ENH_ALL:
            wf.pop(nid, None)
        sw["switch"] = False
        sw["on_true"] = prompt
        sw["on_false"] = prompt

    logger.info("Built workflow with %d image(s), enhancer=%s", n, use_enhancer)
    return wf


# Embedded T2I workflow (your API export; ResolutionSelector replaced by plain width/height)
T2I_EMBEDDED_WORKFLOW = json.loads(
    r'''{"461":{"inputs":{"filename_prefix":"Qwen_image_2.1","format":"png","format.bit_depth":"8-bit","format.input_color_space":"sRGB","images":["459:457",0]},"class_type":"SaveImageAdvanced","_meta":{"title":"Save Image (Advanced)"}},"459:451":{"inputs":{"unet_name":"qwen_image_2.1_int8_convrot.safetensors","weight_dtype":"default"},"class_type":"UNETLoader","_meta":{"title":"Load Diffusion Model"}},"459:452":{"inputs":{"prompt":["459:472",0],"negative_prompt":"","resolution":1024,"clip":["459:453",0]},"class_type":"TextEncodeQwenImage21","_meta":{"title":"Text Encode Qwen Image 2.1"}},"459:453":{"inputs":{"clip_name":"qwen3vl_8b_int8_convrot.safetensors","type":"qwen_image","device":"default"},"class_type":"CLIPLoader","_meta":{"title":"Load CLIP"}},"459:454":{"inputs":{"vae_name":"qwen_image_2.1_vae_bf16.safetensors"},"class_type":"VAELoader","_meta":{"title":"Load VAE"}},"459:456":{"inputs":{"width":1024,"height":1024,"batch_size":1},"class_type":"EmptyLatentImage","_meta":{"title":"Empty Latent Image"}},"459:457":{"inputs":{"samples":["459:458",0],"vae":["459:454",0]},"class_type":"VAEDecode","_meta":{"title":"VAE Decode"}},"459:458":{"inputs":{"seed":447606998181262,"steps":25,"cfg":1,"sampler_name":"euler","scheduler":"simple","denoise":1,"model":["459:480",0],"positive":["459:452",0],"negative":["459:452",1],"latent_image":["459:456",0]},"class_type":"KSampler","_meta":{"title":"KSampler"}},"459:471":{"inputs":{"prompt":"Greyscale fashion editorial portrait of an avant-garde woman tilted upwards in profile, captured with striking high-contrast chiaroscuro lighting. She wears oversized, thick-rimmed circular black sunglasses with matte dark lenses, concealing her upward gaze. Her attire merges high couture with tactical abstraction: a high-necked structural dress tailored from heavyweight fabric featuring a disrupted optical camouflage pattern—interlocking oversized polka dots, pixelated stippling, and organic contour blotches in stark monochrome that mimic military disruptive patterns in a refined runway style. Around her shoulders, asymmetric pleated webbing and tailored cargo straps are integrated seamlessly into the garment’s architecture. In her gloved hand, she clutches a structured matte-leather geometric handbag accented with subtle tactical buckles, utility stitching, and dark brushed-metal hardware. Her skin texture is rendered with hyper-detailed clarity, sculpted by intense, razor-sharp studio key light and deep graphite shadows. The striking background is a vivid mixed-media graphic collage, composed of flat vibrant lime green planes, stark black and white overlapping circles, segmented semi-circles with bold zebra striping, dense micro-halftone dot matrices, and vector topographic contour lines. The clash between monochromatic disruptive camo elements on her clothing and the saturated, retro-futuristic pop-art backdrop creates an intense visual dissonance, emphasizing sharp silhouettes, paper cut-out edges, dynamic compositional balance, and clean graphic novel textures. Absolutely no text, no typography, no letters, no words, no numbers, no logos, no watermark, no captions, pure imagery only.","max_length":4096,"sampling_mode":"on","sampling_mode.temperature":1,"sampling_mode.top_k":20,"sampling_mode.top_p":0.95,"sampling_mode.min_p":0,"sampling_mode.repetition_penalty":1,"sampling_mode.seed":447606998181262,"sampling_mode.presence_penalty":1.5,"thinking":false,"use_default_template":true,"mtp":"auto","clip":["459:473",0],"system_prompt":["459:475",0]},"class_type":"TextGenerate","_meta":{"title":"Generate Text"}},"459:472":{"inputs":{"source":["459:474",0]},"class_type":"PreviewAny","_meta":{"title":"Preview as Text"}},"459:473":{"inputs":{"clip_name":"qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors","type":"stable_diffusion","device":"default"},"class_type":"CLIPLoader","_meta":{"title":"Load CLIP"}},"459:474":{"inputs":{"switch":false,"on_false":"Greyscale fashion editorial portrait of an avant-garde woman tilted upwards in profile, captured with striking high-contrast chiaroscuro lighting. She wears oversized, thick-rimmed circular black sunglasses with matte dark lenses, concealing her upward gaze. Her attire merges high couture with tactical abstraction: a high-necked structural dress tailored from heavyweight fabric featuring a disrupted optical camouflage pattern—interlocking oversized polka dots, pixelated stippling, and organic contour blotches in stark monochrome that mimic military disruptive patterns in a refined runway style. Around her shoulders, asymmetric pleated webbing and tailored cargo straps are integrated seamlessly into the garment’s architecture. In her gloved hand, she clutches a structured matte-leather geometric handbag accented with subtle tactical buckles, utility stitching, and dark brushed-metal hardware. Her skin texture is rendered with hyper-detailed clarity, sculpted by intense, razor-sharp studio key light and deep graphite shadows. The striking background is a vivid mixed-media graphic collage, composed of flat vibrant lime green planes, stark black and white overlapping circles, segmented semi-circles with bold zebra striping, dense micro-halftone dot matrices, and vector topographic contour lines. The clash between monochromatic disruptive camo elements on her clothing and the saturated, retro-futuristic pop-art backdrop creates an intense visual dissonance, emphasizing sharp silhouettes, paper cut-out edges, dynamic compositional balance, and clean graphic novel textures. Absolutely no text, no typography, no letters, no words, no numbers, no logos, no watermark, no captions, pure imagery only.","on_true":["459:471",0]},"class_type":"ComfySwitchNode","_meta":{"title":"If/Else Switch"}},"459:475":{"inputs":{"value":"# Image Prompt Rewriting Expert\n\nYou turn a user's image request into one long English paragraph that describes the\nfinished image as if you were looking at it, plus the aspect ratio it should be\nrendered at. You are not talking to the user and not talking to a renderer: you are\nan observer reporting what is in the frame.\n\nWork through the eight steps below in order. Each step commits one decision; later\nsteps never revise an earlier one.\n\n## Step 1 — Read the brief and split it in two\n\nList what the user has fixed and what they have left open.\n\nFixed, and it must survive into your description unchanged: every string of text\nthey want shown, every named object, every count, every stated colour, every stated\nposition, and the aspect ratio if they gave one. Copy their text strings character\nfor character, in their own script, including punctuation and spacing.\n\nA third thing they may give you is an instruction about the job rather than about the\npicture — \"use double quotes\", \"no hard-edged blocks\", \"4K, no noise\", \"make sure the\ntext is sharp\". That is not content. Obey it silently where it applies and never echo\nit: the description states what is in the frame, never what must be done.\n\nOpen, and you must decide it: everything they did not mention. A three-word request\nand a three-hundred-word request both become a description of the same size, so a\nshort brief means you are inventing most of the frame, not writing less.\n\n## Step 2 — Fix the frame\n\nDecide the orientation from the subject, then pick the ratio.\n\nIf the user states a ratio, use it. Otherwise: `3:2` for anything horizontal and\n`2:3` for anything vertical — these are the two defaults and cover most images.\nUse `1:1` for a square badge, icon, album cover or single centred emblem, `16:9`\nfor a wide cinematic or presentation frame, `1:2` or `9:16` for a phone screen or a\ntall standing banner. `3:4`, `2:1`, `21:9`, `4:3`, `9:21`, `4:5`, `3:1`, `5:4`,\n`1:3` exist but only when the subject or the user really calls for them.\n\nThe ratio lives only in the `wh_ratio` field. Never write a ratio, a resolution, or\na pixel count into the description itself.\n\n## Step 3 — Write the opening sentence\n\nOne sentence, around twenty words. Name the medium, the style, the subject, and the\nbackground or palette; usually name the orientation too:\n\n`The image is a ⟨vertical / wide / square / tall⟩ ⟨style⟩ ⟨photograph · poster · illustration · scene · portrait · infographic · close-up · graphic · page · card · sheet · logo⟩ of ⟨subject⟩, ⟨the background and its palette⟩.`\n\n`This is a …` or a bare `A vertical realistic photograph of …` work equally well. The\nmedium noun is the one part that is never omitted.\n\nThe style word goes here — realistic, photorealistic, minimalist, flat-vector,\ncinematic, watercolour, isometric, editorial, hand-drawn, 3D-rendered, retro. Name\nit once here; you may echo it in the closing sentence.\n\n## Step 4 — Inventory before you write\n\nBefore any more prose, settle two lists.\n\nEvery element that will appear, each with a place in the frame: upper-left,\nacross the top, on the far right, in the lower-third, in the centre, in front of,\nbehind, tucked into the corner. You will need eight to fourteen such positional\nphrases, about ten typically, and they must reach the corners, the edges and the\ncentre — not cluster in the middle.\n\nEvery piece of text that will be legible in the image, in reading order.\n\n## Step 5 — Walk the frame\n\nNow describe it in order. Which order depends on how the frame is filled.\n\n**If the frame is divided into regions** — a poster, a page, an interface, a layout, a\nwide scene with several things in it — walk the regions:\n\n1. The background and the surface it sits on — this comes immediately after the\n   opening sentence, not at the end.\n2. The top band: headline, header bar, sky, ceiling, whatever occupies the top edge.\n3. Down and across the body of the frame: left side, then centre, then right side.\n   Give each region one or two sentences.\n4. The bottom band: footer, foreground, ground plane, base row.\n\n**If one subject fills the frame** — a portrait, a close-up, a single object — walk\nthe subject instead: the background and how far it falls off, then the subject's pose\nand where it is placed in the frame, then head and face, then body and each garment or\nsurface, then what is held or touching it, then whatever little is left at the edges.\nKeep using positional phrases inside the subject — in the upper-left of the frame,\nbehind the left shoulder, along the lower edge — so the frame stays locatable.\n\nRoughly a third of your sentences should open on the positional phrase itself —\n\"On the right side of the frame, …\", \"In the upper-left corner, …\", \"Across the\nlower third, …\" — so the reader always knows where they are looking.\n\nKeep it to one paragraph. Break to a new paragraph only when the image is genuinely\nbuilt from stacked regions — panels, cards, sections, slides — and then one\nparagraph per region, each opening on where that region sits.\n\n## Step 6 — Set every piece of text\n\nSkip this step if nothing in the image is meant to be read — a third of images have\nno legible text at all, and inventing signage for them is a mistake.\n\nOtherwise, for each string from your Step 4 list, in reading order, name where it sits,\nwhat it looks like, and what it says: `a bold black headline across the top reads \"…\"`.\n\nPut the string in straight double quotes, in its own script — Chinese, Russian,\nKorean, Japanese and Arabic text stays in Chinese, Russian, Korean, Japanese and\nArabic. Give its weight, colour, case and relative size. Describe a line break as a\nsecond line rather than putting a real newline inside the string. If a mark is not meant\nto be read — distant signage, a label behind glass, dense body copy — call it\nblurred, indistinct, or too small to read rather than inventing letters. If the image contains a chart\nor a table, its axes, tick labels, legend entries, series and cell values are text\ntoo: write them out.\n\n## Step 7 — Give the lighting its own sentence\n\nEvery image has light in it, and the description always accounts for it: the source,\nits direction, its quality, and the shadows and highlights it leaves. Soft diffused\ndaylight from a window on the left, hard overhead studio light, warm low sun, flat\neven ambient light for a diagram.\n\nOnce the contents are placed, give it a sentence of its own — `The lighting is …` —\nor, if the light is what makes a particular surface look the way it does, fold it into\nthat surface's sentence. Either way it is stated explicitly, not left implied.\n\n## Step 8 — Close with the whole frame\n\nEnd on a single sentence that steps back:\n\n`The overall composition ⟨is / uses / feels⟩ …`\n\n`The composition is …`, `The overall design …`, `The overall mood …`, `The overall\npalette …` and `The image has …` are the same move. Cover balance and symmetry, the\npalette, the style, and the mood in that one sentence. Write exactly one such\nsentence — do not follow it with a second summary.\n\n## Throughout\n\n**Size.** The description runs about twenty sentences and four to five hundred words,\nroughly twenty-five words a sentence. That is the same size whether the brief was three\nwords or three hundred: a dense frame with many regions and a lot of text runs longer, a\nsingle quiet subject runs shorter, but a thin brief never buys a thin description.\n\n**Observe, don't instruct.** Present tense, third person, declarative. No \"you\", no\n\"create\", no \"make sure\", no \"the AI should\". No quality boosters — no \"masterpiece\",\n\"8K\", \"highly detailed\", \"award-winning\".\n\n**Hedge what you cannot be certain of.** An observer describing a picture says\n\"appears to be\", \"likely\", \"suggesting\", and offers a pair — \"a notebook\nor a tablet\", \"wood or dark laminate\" — when the thing is genuinely ambiguous. Do\nthis often; it is the natural register here. Be flatly definite only about what the\nuser fixed.\n\n**Name colours with a modifier, almost never bare.** Deep navy, muted olive, pale\ncream, warm terracotta, soft dusty rose, blue-grey, off-white, charcoal, brownish-\ngreen. Hex codes only if the user gave them.\n\n**Give the material, not just the noun.** Brushed metal, matte plastic, glossy\nceramic, coarse linen, weathered wood, frosted glass, grain, scuffs, condensation,\nvisible brush strokes, paper fibre.\n\n**Enumerate; never summarise.** \"Several items\" and \"various decorations\" are not\ndescriptions. Say what each thing is. Write small counts as words — three, five,\ntwelve — and if something is partly hidden, say so and describe the visible part.\n\n**People get their observable surface.** Build, posture, where they are looking,\nexpression, hair, skin tone, and each garment with its colour and material. Age is a\nlife stage or a decade — a child, a teenager, a young adult, middle-aged, elderly,\nin her thirties — never a number of years. If a face is turned away or cropped, say\nthat instead of describing it.\n\n**Objects by class, not by brand.** A silver laptop, a mirrorless camera, a compact\nhatchback — unless the user named the brand. Photographic and design vocabulary is\nwelcome: shallow depth of field, bokeh, backlit, close-up, negative space,\ngrid, drop shadow.\n\n**Everything holds together physically.** Shadows fall away from the light, reflections\nmatch what is in front of the surface, scale is consistent between neighbouring\nobjects, and a surface reacts to what sits on it. If the user asked for something\nimpossible, describe it as the image shows it and let the rest of the scene stay\ncoherent around it.\n\n## Language\n\nThe description is always in English, whatever language the request arrives in. The\nonly exception is text shown inside the image, which stays in its own script.\n\n## Output format\n\n- Return the description and nothing else: one continuous paragraph of English, in a single line\nstarting on the very first character of your reply.\n- No JSON, no braces, no key names, no labels, no headings, no markdown, no code fences, and no quotation marks around the paragraph.\n- No preamble, no acknowledgement, no explanation, no summary, no notes, no closing remarks, no questions.\n- No ratio, no resolution, no pixel count, no timestamps.\n\nYour whole reply is used as the image prompt, so every extra word you add becomes part of the image.\n"},"class_type":"PrimitiveStringMultiline","_meta":{"title":"Text (System Prompt)"}},"459:480":{"inputs":{"device":"auto","dtype":"default","model":["459:451",0]},"class_type":"QwenImage21Cache","_meta":{"title":"Qwen Image 2.1 Cache"}}}'''
)


def _load_t2i_workflow(path: str, inline_json: str) -> Dict[str, Any]:
    """Priority: t2i_workflow_json valve > t2i_workflow_path file > embedded copy."""
    if inline_json.strip():
        return json.loads(inline_json)
    if path.strip():
        if not os.path.isfile(path):
            raise FileNotFoundError(f"T2I workflow JSON not found at '{path}'.")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return copy.deepcopy(T2I_EMBEDDED_WORKFLOW)


def _resolve_size(aspect_ratio: str, megapixels: float, multiple: int = 16):
    """'16:9' + 1.0 MP -> (width, height), both multiples of `multiple`."""
    m = re.match(
        r"^\s*(\d+(?:\.\d+)?)\s*[:/xX]\s*(\d+(?:\.\d+)?)\s*$", aspect_ratio or ""
    )
    if not m:
        raise ValueError(
            f"Invalid aspect_ratio '{aspect_ratio}'. Use the form 'W:H', e.g. '16:9'."
        )
    rw, rh = float(m.group(1)), float(m.group(2))
    if rw <= 0 or rh <= 0 or max(rw, rh) / min(rw, rh) > 4:
        raise ValueError("aspect_ratio must be positive and no more extreme than 4:1.")
    total = megapixels * 1024 * 1024
    height = (total * rh / rw) ** 0.5
    width = height * rw / rh

    def snap(v: float) -> int:
        return max(multiple, int(round(v / multiple)) * multiple)

    return snap(width), snap(height)


def _build_t2i_workflow(
    base: Dict[str, Any],
    prompt: str,
    width: int,
    height: int,
    seed: int,
    use_enhancer: bool,
) -> Dict[str, Any]:
    wf = copy.deepcopy(base)

    lat = wf[T2I_LATENT]["inputs"]
    lat["width"] = width
    lat["height"] = height

    wf[T2I_KSAMPLER]["inputs"]["seed"] = seed

    sw = wf[T2I_PROMPT_SWITCH]["inputs"]
    if use_enhancer:
        gen = wf[T2I_ENH_GEN]["inputs"]
        gen["prompt"] = prompt
        gen["sampling_mode.seed"] = seed
        sw["switch"] = True
        sw["on_true"] = [T2I_ENH_GEN, 0]
        sw["on_false"] = prompt
    else:
        for nid in T2I_ENH_ALL:
            wf.pop(nid, None)
        sw["switch"] = False
        sw["on_true"] = prompt
        sw["on_false"] = prompt

    logger.info("Built T2I workflow %dx%d, enhancer=%s", width, height, use_enhancer)
    return wf


# ─── Image helpers ─────────────────────────────────────────────────────────────


def _auth_headers(request: Any) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if request is None:
        return headers
    try:
        auth = request.headers.get("Authorization") or request.headers.get(
            "authorization"
        )
        if auth:
            headers["Authorization"] = auth
        else:
            token = request.cookies.get("token")
            if token:
                headers["Authorization"] = f"Bearer {token}"
    except Exception:
        pass
    return headers


async def _bytes_from_url(url: str, owui_base: str, request: Any) -> Optional[bytes]:
    if not url:
        return None
    if url.startswith("data:"):
        try:
            return base64.b64decode(url.split(",", 1)[1])
        except Exception as exc:
            logger.warning("base64 decode failed: %s", exc)
            return None
    if url.startswith("/"):
        full = owui_base.rstrip("/") + url
        headers = _auth_headers(request)
    elif url.startswith(("http://", "https://")):
        full = url
        headers = {}
    else:
        logger.warning("Unrecognised image URL: %.80s", url)
        return None
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(full, headers=headers) as r:
                if r.status == 200:
                    return await r.read()
                logger.warning("Fetch %.80s -> HTTP %d", url, r.status)
    except Exception as exc:
        logger.warning("Fetch error: %s", exc)
    return None


def _image_urls_in_message(msg: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    content = msg.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                obj = part.get("image_url") or {}
                u = obj.get("url") or obj.get("src") or ""
                if u:
                    urls.append(u)
    for f in msg.get("files") or []:
        if isinstance(f, dict) and f.get("type") == "image" and f.get("url"):
            if f["url"] not in urls:
                urls.append(f["url"])
    return urls


def _collect_message_images(
    messages: List[Dict[str, Any]], latest_only: bool
) -> List[str]:
    """Image URLs in chronological order (upload order = image1, image2, ...)."""
    if latest_only:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                urls = _image_urls_in_message(msg)
                if urls:
                    return urls
        return []
    out: List[str] = []
    for msg in messages:
        out.extend(_image_urls_in_message(msg))
    return out


# ─── ComfyUI helpers ───────────────────────────────────────────────────────────


async def _upload_image_to_comfyui(http_url: str, data: bytes, filename: str) -> str:
    form = aiohttp.FormData()
    form.add_field(
        "image", io.BytesIO(data), filename=filename, content_type="image/png"
    )
    form.add_field("type", "input")
    form.add_field("overwrite", "true")
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{http_url}/upload/image", data=form) as r:
            r.raise_for_status()
            return (await r.json()).get("name", filename)


async def _submit_and_wait(
    http_url: str, workflow: Dict[str, Any], client_id: str, max_wait: int
) -> Dict[str, Any]:
    ws_base = http_url.replace("http://", "ws://").replace("https://", "wss://")
    loop = asyncio.get_event_loop()
    start = loop.time()

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{http_url}/prompt", json={"prompt": workflow, "client_id": client_id}
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"ComfyUI /prompt returned {resp.status}: {await resp.text()}"
                )
            prompt_id = (await resp.json()).get("prompt_id")
            if not prompt_id:
                raise RuntimeError("ComfyUI did not return a prompt_id")
            logger.info("Prompt queued: %s", prompt_id)

        async def _history() -> Optional[Dict[str, Any]]:
            try:
                async with session.get(f"{http_url}/history/{prompt_id}") as hr:
                    if hr.status == 200:
                        h = await hr.json()
                        if prompt_id in h:
                            return h[prompt_id]
            except Exception:
                pass
            return None

        try:
            async with session.ws_connect(f"{ws_base}/ws?clientId={client_id}") as ws:
                last_poll = 0.0
                while True:
                    now = loop.time()
                    if now - start > max_wait:
                        raise TimeoutError(f"Timed out after {max_wait}s")
                    if now - last_poll > 3.0:
                        last_poll = now
                        job = await _history()
                        if job:
                            return job
                    try:
                        msg = await ws.receive(timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            m = json.loads(msg.data)
                        except json.JSONDecodeError:
                            continue
                        d = m.get("data", {})
                        if d.get("prompt_id") != prompt_id:
                            continue
                        t = m.get("type", "")
                        if t == "execution_error":
                            raise RuntimeError(
                                f"ComfyUI error on node {d.get('node_id', '?')}: "
                                f"{d.get('exception_message', 'unknown')}"
                            )
                        if t in ("executed", "execution_success", "execution_cached"):
                            job = await _history()
                            if job:
                                return job
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break
        except (aiohttp.ClientError, OSError) as exc:
            logger.warning("WS unavailable (%s) - polling only", exc)

        while loop.time() - start <= max_wait:
            await asyncio.sleep(2)
            job = await _history()
            if job:
                return job
        raise TimeoutError(f"Polling timed out after {max_wait}s")


def _extract_output_images(job: Dict[str, Any]) -> List[Dict[str, str]]:
    imgs: List[Dict[str, str]] = []
    for node_output in job.get("outputs", {}).values():
        for img in node_output.get("images", []):
            if img.get("type") == "output":
                imgs.append(img)
    return imgs


async def _fetch_from_comfyui(http_url: str, meta: Dict[str, str]) -> Optional[bytes]:
    params = {"filename": meta["filename"], "type": meta.get("type", "output")}
    if meta.get("subfolder"):
        params["subfolder"] = meta["subfolder"]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{http_url}/view", params=params) as r:
                r.raise_for_status()
                return await r.read()
    except Exception as exc:
        logger.warning("Failed to fetch output from ComfyUI: %s", exc)
        return None


async def _upload_to_owui(
    owui_base: str, data: bytes, filename: str, request: Any
) -> Optional[str]:
    headers = {"accept": "application/json", **_auth_headers(request)}
    form = aiohttp.FormData()
    form.add_field(
        "file", io.BytesIO(data), filename=filename, content_type="image/png"
    )
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{owui_base.rstrip('/')}/api/v1/files/", data=form, headers=headers
            ) as r:
                if r.status in (200, 201):
                    fid = (await r.json()).get("id")
                    if fid:
                        return f"/api/v1/files/{fid}/content"
                logger.warning("OWUI upload failed: HTTP %d", r.status)
    except Exception as exc:
        logger.warning("OWUI upload error: %s", exc)
    return None


async def _resolve_display_url(
    http_url: str, meta: Dict[str, str], owui_base: str, request: Any, filename: str
) -> str:
    data = await _fetch_from_comfyui(http_url, meta)
    if data is None:
        return ""
    url = await _upload_to_owui(owui_base, data, filename, request)
    if url:
        return url
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


# ─── LLM offload helpers ───────────────────────────────────────────────────────


async def _unload_ollama(base_url: str) -> str:
    base = base_url.rstrip("/")
    unloaded: List[str] = []
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{base}/api/ps", timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status != 200:
                    return f"Ollama /api/ps -> HTTP {r.status} (skipped)"
                data = await r.json()
            for m in data.get("models", []):
                name = m.get("name")
                if not name:
                    continue
                try:
                    async with s.post(
                        f"{base}/api/generate",
                        json={"model": name, "keep_alive": 0},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as ur:
                        await ur.read()
                        if ur.status in (200, 204):
                            unloaded.append(name)
                except Exception as exc:
                    logger.warning("Ollama unload %s failed: %s", name, exc)
        return f"Ollama: unloaded {unloaded}" if unloaded else "Ollama: nothing loaded"
    except Exception as exc:
        return f"Ollama offload skipped ({exc})"


async def _unload_llama_cpp(base_url: str) -> str:
    base = base_url.rstrip("/")
    unloaded: List[str] = []
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{base}/v1/models", timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status != 200:
                    return f"llama.cpp /v1/models -> HTTP {r.status} (skipped)"
                data = await r.json()
            for m in data.get("data", []):
                st = m.get("status", {})
                val = st.get("value", "") if isinstance(st, dict) else st
                if val != "loaded":
                    continue
                try:
                    async with s.post(
                        f"{base}/models/unload",
                        json={"model": m["id"]},
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as ur:
                        if ur.status in (200, 204):
                            unloaded.append(m["id"])
                except Exception as exc:
                    logger.warning("llama.cpp unload %s failed: %s", m["id"], exc)
        return (
            f"llama.cpp: unloaded {unloaded}" if unloaded else "llama.cpp: none loaded"
        )
    except Exception as exc:
        return f"llama.cpp offload skipped ({exc})"


# ─── Tool class ────────────────────────────────────────────────────────────────


class Tools:
    class Valves(BaseModel):
        comfyui_url: str = Field(default="http://localhost:8188")
        owui_internal_base: str = Field(
            default="http://localhost:8080",
            description="Server-side base URL OWUI can reach itself on.",
        )
        workflow_path: str = Field(
            default="",
            description=(
                "OPTIONAL override: path (inside the OWUI container) to an API-format "
                "workflow export. Leave empty to use the workflow embedded in this tool."
            ),
        )
        workflow_json: str = Field(
            default="",
            description="Optional: paste the API-format workflow JSON here instead.",
        )
        ollama_url: str = Field(default="http://localhost:11434")
        llama_cpp_url: str = Field(default="http://localhost:8082")
        unload_ollama: bool = Field(default=True)
        unload_llama_cpp: bool = Field(default=True)
        use_prompt_enhancer: bool = Field(
            default=False,
            description=(
                "Run the workflow's built-in prompt enhancer (TextGenerate node) "
                "on the user's instruction. If False the instruction is used as-is "
                "and the enhancer nodes are removed from the graph."
            ),
        )
        latest_message_images_only: bool = Field(
            default=True,
            description=(
                "True: use images from the most recent user message that has "
                "images. False: use every image in the chat (oldest first)."
            ),
        )
        max_wait_seconds: int = Field(default=900)
        seed: int = Field(default=-1, description="-1 = random each run.")
        t2i_workflow_path: str = Field(
            default="",
            description="OPTIONAL override: path to an API-format T2I workflow export.",
        )
        t2i_workflow_json: str = Field(
            default="",
            description="Optional: paste the API-format T2I workflow JSON here.",
        )
        t2i_default_megapixels: float = Field(default=1.0)
        t2i_max_megapixels: float = Field(
            default=2.0, description="Upper limit so the LLM can't request OOM sizes."
        )

    class UserValves(BaseModel):
        unload_ollama: bool = Field(default=True)
        unload_llama_cpp: bool = Field(default=True)
        use_prompt_enhancer: bool = Field(default=False)
        seed: int = Field(default=-1)

    def __init__(self):
        self.valves = self.Valves()

    def _uv(self, user_valves: Any, name: str) -> Any:
        if user_valves is not None and hasattr(user_valves, name):
            return getattr(user_valves, name)
        return getattr(self.valves, name)

    async def _status(self, emitter, text: str, done: bool = False) -> None:
        if emitter:
            await emitter(
                {"type": "status", "data": {"description": text, "done": done}}
            )

    async def qwen_image_edit(
        self,
        prompt: str,
        image_urls: str = "",
        __event_emitter__: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        __user__: Optional[Dict[str, Any]] = None,
        __messages__: Optional[List[Dict[str, Any]]] = None,
        __request__: Optional[Any] = None,
    ) -> str:
        """
        Edit or composite 1-10 images with Qwen Image 2.1.

        The images are taken automatically from the images the user uploaded in
        the conversation, in upload order. Do NOT try to copy image data into
        any argument; leave image_urls empty unless explicitly needed.

        In the prompt, refer to the images as image1, image2, ... imageN in the
        order they were uploaded, e.g. "dress the person in image1 in the
        clothing from image2" or "place the object from image3 into the scene
        of image1".

        :param prompt: Edit instruction referencing image1..imageN.
        :param image_urls: Optional. Newline/comma separated image URLs
            ("/api/v1/files/<id>/content" or data: URIs). Leave empty to use the
            images uploaded in the chat.
        """
        emitter = __event_emitter__
        user_valves = (__user__ or {}).get("valves")
        owui_base = self.valves.owui_internal_base
        http_url = self.valves.comfyui_url.rstrip("/")

        # 1. Gather images
        await self._status(emitter, "🔍 Resolving source images…")
        candidates: List[str] = []
        if image_urls.strip():
            for part in image_urls.replace(",\n", "\n").split("\n"):
                part = part.strip()
                if part:
                    candidates.append(part)
        if not candidates and __messages__:
            candidates = _collect_message_images(
                __messages__, self.valves.latest_message_images_only
            )

        images: List[bytes] = []
        seen = set()
        for url in candidates:
            data = await _bytes_from_url(url, owui_base, __request__)
            if not data:
                continue
            h = hashlib.sha1(data).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            images.append(data)

        if len(images) > MAX_IMAGES:
            images = images[-MAX_IMAGES:]  # keep the most recent 10
        n = len(images)
        if n == 0:
            await self._status(emitter, "❌ No images found.", done=True)
            return "❌ No source images found. Attach 1-10 images and try again."

        # 2. Load workflow template
        try:
            base = _load_base_workflow(
                self.valves.workflow_path, self.valves.workflow_json
            )
        except Exception as exc:
            await self._status(emitter, f"❌ Workflow load failed: {exc}", done=True)
            return f"❌ Could not load the workflow template: {exc}"

        # 3. Free VRAM
        if self._uv(user_valves, "unload_ollama"):
            await self._status(emitter, "⬇️ Unloading Ollama from VRAM…")
            logger.info(await _unload_ollama(self.valves.ollama_url))
        if self._uv(user_valves, "unload_llama_cpp"):
            await self._status(emitter, "⬇️ Flushing llama.cpp VRAM…")
            logger.info(await _unload_llama_cpp(self.valves.llama_cpp_url))

        # 4. Upload to ComfyUI
        await self._status(emitter, f"📤 Uploading {n} image(s) to ComfyUI…")
        run_id = uuid.uuid4().hex[:8]
        comfy_files: List[str] = []
        for i, data in enumerate(images):
            try:
                comfy_files.append(
                    await _upload_image_to_comfyui(
                        http_url, data, f"owui_qwen21_{run_id}_{i + 1}.png"
                    )
                )
            except Exception as exc:
                await self._status(
                    emitter, f"❌ Upload failed for image {i + 1}", done=True
                )
                return f"❌ Failed to upload image {i + 1} to ComfyUI: {exc}"

        # 5. Build + run
        seed = int(self._uv(user_valves, "seed"))
        if seed < 0:
            seed = random.randint(1, 2**32 - 1)
        try:
            workflow = _build_workflow(
                base,
                comfy_files,
                prompt,
                seed,
                bool(self._uv(user_valves, "use_prompt_enhancer")),
            )
        except KeyError as exc:
            await self._status(emitter, "❌ Workflow node mismatch", done=True)
            return (
                f"❌ Node {exc} missing from the workflow JSON. Update the N_* "
                "node-ID constants at the top of the tool to match your export."
            )

        await self._status(emitter, f"🎨 Running Qwen Image 2.1 ({n} image(s))…")
        try:
            job = await _submit_and_wait(
                http_url, workflow, str(uuid.uuid4()), self.valves.max_wait_seconds
            )
        except TimeoutError as exc:
            await self._status(emitter, f"⏱️ {exc}", done=True)
            return f"⏱️ {exc}"
        except Exception as exc:
            await self._status(emitter, f"❌ ComfyUI error: {exc}", done=True)
            return f"❌ ComfyUI error: {exc}"

        # 6. Output
        outputs = _extract_output_images(job)
        if not outputs:
            await self._status(emitter, "⚠️ No output images.", done=True)
            return (
                "⚠️ ComfyUI finished but returned no images. Check that the "
                "Qwen Image 2.1 custom nodes and model files are installed."
            )

        await self._status(emitter, "💾 Storing result…")
        stored = 0
        for meta in outputs:
            fname = f"qwen21_edit_{n}img_{uuid.uuid4().hex[:6]}.png"
            url = await _resolve_display_url(
                http_url, meta, owui_base, __request__, fname
            )
            if not url:
                continue
            if emitter:
                await emitter(
                    {
                        "type": "files",
                        "data": {
                            "files": [
                                {
                                    "type": "image",
                                    "url": url,
                                    "name": fname,
                                    "collection_name": "",
                                }
                            ]
                        },
                    }
                )
            stored += 1

        if not stored:
            await self._status(emitter, "❌ Could not retrieve result.", done=True)
            return "❌ Workflow completed but the result image could not be retrieved."

        await self._status(emitter, "✅ Image edit complete!", done=True)
        return (
            f"Image edit completed using {n} input image(s). The result is attached "
            "to this message as a file; do NOT include markdown image syntax. "
            "Briefly confirm to the user that the edit is done."
        )

    async def qwen_image_generate(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        megapixels: float = 0.0,
        __event_emitter__: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        __user__: Optional[Dict[str, Any]] = None,
        __request__: Optional[Any] = None,
    ) -> str:
        """
        Generate a NEW image from a text description with Qwen Image 2.1
        (text-to-image). Use this when the user wants an image created from
        scratch. If the user wants to modify, restyle or combine images they
        uploaded, use qwen_image_edit instead.

        :param prompt: Description of the image to generate. Include the exact
            text for any words that must appear in the image.
        :param aspect_ratio: Image shape as 'W:H', e.g. '1:1', '3:2', '2:3',
            '16:9', '9:16', '4:3', '3:4', '21:9'. Use 2:3 or 9:16 for vertical
            subjects, 3:2 or 16:9 for horizontal ones.
        :param megapixels: Optional size in megapixels (0.25-2.0). Leave 0 to
            use the default (about 1.0).
        """
        emitter = __event_emitter__
        user_valves = (__user__ or {}).get("valves")
        owui_base = self.valves.owui_internal_base
        http_url = self.valves.comfyui_url.rstrip("/")

        if not prompt or not prompt.strip():
            return "❌ Empty prompt. Describe the image to generate."

        # 1. Size
        mp = (
            megapixels
            if megapixels and megapixels > 0
            else self.valves.t2i_default_megapixels
        )
        mp = max(0.25, min(mp, self.valves.t2i_max_megapixels))
        try:
            width, height = _resolve_size(aspect_ratio, mp)
        except ValueError as exc:
            await self._status(emitter, f"❌ {exc}", done=True)
            return f"❌ {exc}"

        # 2. Workflow template
        try:
            base = _load_t2i_workflow(
                self.valves.t2i_workflow_path, self.valves.t2i_workflow_json
            )
        except Exception as exc:
            await self._status(
                emitter, f"❌ T2I workflow load failed: {exc}", done=True
            )
            return f"❌ Could not load the T2I workflow template: {exc}"

        # 3. Free VRAM
        if self._uv(user_valves, "unload_ollama"):
            await self._status(emitter, "⬇️ Unloading Ollama from VRAM…")
            logger.info(await _unload_ollama(self.valves.ollama_url))
        if self._uv(user_valves, "unload_llama_cpp"):
            await self._status(emitter, "⬇️ Flushing llama.cpp VRAM…")
            logger.info(await _unload_llama_cpp(self.valves.llama_cpp_url))

        # 4. Build
        seed = int(self._uv(user_valves, "seed"))
        if seed < 0:
            seed = random.randint(1, 2**32 - 1)
        try:
            workflow = _build_t2i_workflow(
                base,
                prompt.strip(),
                width,
                height,
                seed,
                bool(self._uv(user_valves, "use_prompt_enhancer")),
            )
        except KeyError as exc:
            await self._status(emitter, "❌ Workflow node mismatch", done=True)
            return (
                f"❌ Node {exc} missing from the T2I workflow JSON. Update the T2I_* "
                "node-ID constants at the top of the tool to match your export."
            )

        # 5. Run
        await self._status(
            emitter, f"🎨 Generating {width}x{height} with Qwen Image 2.1…"
        )
        try:
            job = await _submit_and_wait(
                http_url, workflow, str(uuid.uuid4()), self.valves.max_wait_seconds
            )
        except TimeoutError as exc:
            await self._status(emitter, f"⏱️ {exc}", done=True)
            return f"⏱️ {exc}"
        except Exception as exc:
            await self._status(emitter, f"❌ ComfyUI error: {exc}", done=True)
            return f"❌ ComfyUI error: {exc}"

        # 6. Output
        outputs = _extract_output_images(job)
        if not outputs:
            await self._status(emitter, "⚠️ No output images.", done=True)
            return (
                "⚠️ ComfyUI finished but returned no images. Check that the "
                "Qwen Image 2.1 custom nodes and model files are installed."
            )

        await self._status(emitter, "💾 Storing result…")
        stored = 0
        for meta in outputs:
            fname = f"qwen21_t2i_{uuid.uuid4().hex[:6]}.png"
            url = await _resolve_display_url(
                http_url, meta, owui_base, __request__, fname
            )
            if not url:
                continue
            if emitter:
                await emitter(
                    {
                        "type": "files",
                        "data": {
                            "files": [
                                {
                                    "type": "image",
                                    "url": url,
                                    "name": fname,
                                    "collection_name": "",
                                }
                            ]
                        },
                    }
                )
            stored += 1

        if not stored:
            await self._status(emitter, "❌ Could not retrieve result.", done=True)
            return "❌ Workflow completed but the result image could not be retrieved."

        await self._status(emitter, "✅ Image generated!", done=True)
        return (
            f"Image generated ({width}x{height}). The result is attached to this "
            "message as a file; do NOT include markdown image syntax. "
            "Briefly confirm to the user that the image is done."
        )
