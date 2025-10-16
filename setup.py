from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="todoai-cli",
    version="0.1.0",
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
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=[
        # Remove todoforai_edge dependency for now
        # Users need to install it separately: pip install -e ../edge
    ],
    entry_points={
        "console_scripts": [
            "todoai_cli=todoai_cli.cli:main",
        ],
    },
)