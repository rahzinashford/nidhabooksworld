"""Local development entrypoint.

Reads PORT from the environment so it can run under the Replit workflow
system, defaulting to 8000 for plain local use.
"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
