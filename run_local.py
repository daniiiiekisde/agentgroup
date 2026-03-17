"""run_local.py – Launch AgentGroup in local mode.

This starts TWO servers concurrently:
  1. Gradio app  on http://localhost:7861  (agent config + Run button)
  2. Live chat   on http://localhost:7860  (WhatsApp-style real-time feed)

Usage:
    python run_local.py

Environment variables are loaded from .env automatically.
Open http://localhost:7860 in your browser for the live group chat.
Open http://localhost:7861 to configure agents and start a session.
"""
import threading
import uvicorn
from core.live_chat import create_app as create_chat_app

CHAT_PORT   = 7860
GRADIO_PORT = 7861


def _start_live_chat():
    app = create_chat_app()
    uvicorn.run(app, host="0.0.0.0", port=CHAT_PORT, log_level="warning")


def _start_gradio():
    # Import app *after* live_chat is available so orchestrator can post messages
    import app as gradio_app
    gradio_app.demo.launch(
        server_name="0.0.0.0",
        server_port=GRADIO_PORT,
        share=False,
        quiet=True,
    )


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  🤖 AgentGroup – Local Mode")
    print("=" * 60)
    print(f"  💬 Live group chat  → http://localhost:{CHAT_PORT}")
    print(f"  ⚙️  Agent config UI → http://localhost:{GRADIO_PORT}")
    print("=" * 60 + "\n")

    # Start live chat server in background thread
    chat_thread = threading.Thread(target=_start_live_chat, daemon=True)
    chat_thread.start()

    # Start Gradio in main thread (blocking)
    _start_gradio()
