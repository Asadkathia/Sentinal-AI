from setuptools import find_packages, setup

setup(
    name="smart-code-reviewer",
    version="0.1.0",
    description="Smart Code Reviewer: CLI + local web UI",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    include_package_data=True,
    package_data={"scr": ["templates/*.html"]},
    install_requires=[
        "typer>=0.12.0",
        "fastapi>=0.115.0",
        "uvicorn>=0.30.0",
        "jinja2>=3.1.0",
        "pydantic>=2.8.0",
        "pyyaml>=6.0.0",
        "httpx>=0.27.0",
        "eval_type_backport>=0.2.2",
    ],
    extras_require={"dev": ["pytest>=8.0.0", "pytest-cov>=5.0.0"]},
    entry_points={"console_scripts": ["scr=scr.cli:run"]},
)
