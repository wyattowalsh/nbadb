(installation)=

# Installation

```{warning}
These installation instructions are intended for **MacOS** machines only. If you are using a different OS and need help, leave a comment in the [project discussions](https://github.com/wyattowalsh/nba-db/discussions)
```

```{note} Your present working directory (**PWD**) should be the project root directory.
From terminal, this can be achieved by typing "cd " (notice the space after "cd") and then dragging the project root directory into the terminal window. This will automatically fill in the path to the directory. Press enter and you will be in the correct location to run the setup script.
```

---

## Step #1: Install Homebrew

```{code-block} console
:caption: run the following snippet in the `terminal` app
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

```{warning}
Make sure to follow along in the terminal and follow the instructions. Ensure that the three commands at the bottom (lines starting with: echo echo eval) are properly executed (one at a time) as these will enabled proper Homebrew installation and future usage.
```

## Step #2: Run Included Setup Script

```{code-block} console
:caption: run the following snippet in the `terminal` app
chmod u+x ./utils/setup.sh && chmod 744 ./utils/setup.sh && ./utils/setup.sh
```

```{tip}
The first two commands properly set the permissions for setup script and the last command runs the script. The setup script creates [a poetry virtual environment](https://python-poetry.org/), installs all related dependencies, activates the environment, and ensures any other necessary initializations.
```

## Step #3: Install Dependencies Within a Virtual Environment using _Poetry_

```{code-block} console
:caption: run the following snippet in the `terminal` app
poetry shell && poetry install
```

## Step #4: Use Make Script to Run Various Project Functionalities

```{code-block} console
:caption: run the following snippet in the `terminal` app
make jupyter lab
```

```{code-block} console
:caption: run the following snippet in the `terminal` app
make docs server
```

```{code-block} console
:caption: run the following snippet in the `terminal` app
make docs build html
```

```{code-block} console
:caption: run the following snippet in the `terminal` app
make tests
```

```{code-block} console
:caption: run the following snippet in the `terminal` app
make format
```
