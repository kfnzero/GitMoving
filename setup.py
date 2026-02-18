from setuptools import setup, find_packages

setup(
    name="gitmoving",
    version="0.1.0",
    description="Migrate Git repositories across GitHub, GitLab, and Bitbucket while preserving history",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "PyGithub>=2.1.1",
        "python-gitlab>=4.4.0",
        "requests>=2.31.0",
        "click>=8.1.7",
        "rich>=13.7.0",
        "keyring>=24.3.0",
        "pydantic>=2.5.0",
        "python-dotenv>=1.0.0",
        "textual>=0.47.0",
    ],
    entry_points={
        "console_scripts": [
            "gitmoving=gitmoving.cli:main",
        ],
    },
)
