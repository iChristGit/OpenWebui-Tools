"""
title: QR Code Generator
author: iChrist
description: Generates QR codes for URLs or text and embeds them directly in chat.
required_open_webui_version: 0.4.0
requirements: qrcode[pil]
version: 0.1.0
license: MIT
"""

import io
import base64
import qrcode
from fastapi.responses import HTMLResponse


class Tools:
    def __init__(self):
        self.valves = self.Valves()

    class Valves:
        # Add customizable settings here if needed later
        pass

    async def generate_qr_code(
        self, content: str, __event_emitter__=None
    ) -> HTMLResponse:
        """
        Creates a QR code for the given text, URL, or data and embeds it directly in the chat.
        :param content: The text, link, or data to encode in the QR code
        """
        try:
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=4,
            )
            qr.add_data(content)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            # Convert to base64
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            b64_string = base64.b64encode(buffered.getvalue()).decode()

            # Create full HTML document for Rich UI Embedding
            html_content = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            margin: 0;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            background: #ffffff;
            font-family: system-ui, -apple-system, sans-serif;
        }}
        .qr-container {{
            text-align: center;
        }}
        img {{
            max-width: 250px;
            height: auto;
            border: 4px solid #333;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .label {{
            margin-top: 10px;
            color: #666;
            font-size: 14px;
            word-break: break-all;
        }}
    </style>
</head>
<body>
    <div class="qr-container">
        <img src="data:image/png;base64,{b64_string}" alt="QR Code" />
        <div class="label">{content}</div>
    </div>
    <script>
        // Report height to parent so the iframe auto-sizes
        function reportHeight() {{
            const h = document.documentElement.scrollHeight;
            parent.postMessage({{ type: 'iframe:height', height: h }}, '*');
        }}
        window.addEventListener('load', reportHeight);
    </script>
</body>
</html>"""

            return HTMLResponse(
                content=html_content, headers={"Content-Disposition": "inline"}
            )

        except Exception as e:
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": f"❌ Error: {str(e)}",
                            "done": True,
                            "hidden": False,
                        },
                    }
                )
            # Return an HTML error page
            error_html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ padding: 20px; font-family: system-ui, sans-serif; color: #dc2626; }}
    </style>
</head>
<body>
    <p>Failed to generate QR code: {str(e)}</p>
    <script>
        function reportHeight() {{
            const h = document.documentElement.scrollHeight;
            parent.postMessage({{ type: 'iframe:height', height: h }}, '*');
        }}
        window.addEventListener('load', reportHeight);
    </script>
</body>
</html>"""
            return HTMLResponse(
                content=error_html,
                status_code=500,
                headers={"Content-Disposition": "inline"},
            )
