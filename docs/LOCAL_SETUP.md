# Local setup guide

These steps are for Windows PowerShell and Python 3.11.

## 1. Install prerequisites

- Git for Windows
- Python 3.11

## 2. Clone the project

```powershell
git clone https://github.com/Magic255/sales-dash.git
cd sales-dash
```

## 3. Create a virtual environment

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can use Command Prompt instead:

```bat
.venv\Scripts\activate.bat
```

## 4. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

## 5. Create local configuration

```powershell
Copy-Item .env.example .env
```

Open `.env` and replace the placeholder `SECRET_KEY` with a long random value. Keep `.env` on your computer; never upload or commit it.

## 6. Start the development server

```powershell
python backend\run.py
```

Open `http://127.0.0.1:5000` in your browser. The API health endpoint is `http://127.0.0.1:5000/api/health`.

## 7. Run quality checks

In another terminal with the virtual environment activated:

```powershell
ruff check .
pytest
```

GitHub Actions also runs these checks on pushes to `main` and pull requests targeting `main`.

## Troubleshooting

- If `py -3.11` is not recognized, install Python 3.11 and enable the Python Launcher during installation.
- If port 5000 is already in use, set a different `PORT` value in your local `.env` file.
- Do not put database files, real customer records, credentials, API keys, or tokens in the repository.
