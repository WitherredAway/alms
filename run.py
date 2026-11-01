"""Start ALMS: python run.py [--port 5000] [--no-browser] [--reset]"""
import argparse
import os
import shutil
import subprocess
import threading
import webbrowser

from alms import create_app


def open_browser(url):
    # Under WSL, open the URL in the Windows default browser.
    for cmd in (["wslview", url], ["explorer.exe", url], ["cmd.exe", "/c", "start", "", url]):
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue
    webbrowser.open(url)


def main():
    p = argparse.ArgumentParser(description="Automated Library Management System")
    p.add_argument("--host", default=os.environ.get("ALMS_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("ALMS_PORT", "5000")))
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--reset", action="store_true", help="Wipe the database and reload demo data")
    p.add_argument("--debug", action="store_true", help="Use the Flask dev server with auto-reload")
    args = p.parse_args()

    app = create_app()
    if args.reset:
        with app.app_context():
            from alms.seed import seed_demo

            seed_demo()
        print("Demo data reset.")

    url = f"http://localhost:{args.port}"
    print(f"\n  ALMS is running at {url}\n  Demo logins: ADM001 / LIB001 / STU001 … (password: demo123)\n  Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(1.2, open_browser, args=(url,)).start()
    if args.debug:
        app.run(host=args.host, port=args.port, debug=True, use_reloader=False)
    else:
        from waitress import serve

        serve(app, host=args.host, port=args.port, threads=8)


if __name__ == "__main__":
    main()
