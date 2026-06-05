import os
import sys
import subprocess

def main():
    code_dir = os.path.join(os.path.dirname(__file__), "code")
    print("Starting Week 8 Web App...")
    try:
        # Run uvicorn from within the code directory using its local uv environment
        subprocess.run(
            ["uv", "run", "python", "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
            cwd=code_dir,
            check=True
        )
    except subprocess.CalledProcessError:
        print("Error: Failed to start the web app.")
        sys.exit(1)

if __name__ == "__main__":
    main()
