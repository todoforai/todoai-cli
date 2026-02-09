from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="todoai-cli",
    version="0.1.6",
    author="TODOforAI",
    author_email="support@todoforai.com",
    description="Command-line interface for TODOforAI Edge",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/todoforai/todoai-cli",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.10",
    install_requires=[
        "todoforai-edge-cli>=0.12.3",
        "prompt_toolkit>=3.0.0",
    ],
    entry_points={
        "console_scripts": [
            "todoai-cli=todoai_cli.cli:main",
        ],
    },
)