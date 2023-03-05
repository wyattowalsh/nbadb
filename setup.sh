#!/bin/bash

# Update homebrew recipes
echo "Updating homebrew..."
brew update

# Install git + gh (GitHub CLI)
echo "Installing Git..."
brew install git
brew install gh

# Install Make
echo "Installing Make..."
brew install make

# Install Python via pyenv
echo "Installing Python via pyenv..."
brew install pyenv
echo 'alias brew='env PATH="${PATH//$(pyenv root)\/shims:/}" brew'' >> .profile
echo 'alias brew='env PATH="${PATH//$(pyenv root)\/shims:/}" brew'' >> .zprofile
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.profile
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zprofile
echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.profile
echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zprofile
echo 'eval "$(pyenv init -)"' >> ~/.profile
echo 'eval "$(pyenv init -)"' >> ~/.zprofile
exec "$SHELL"

# Install Sphinx Docs
echo "Installing Sphinx Docs..."
brew install sphinx-doc
echo 'export PATH="/opt/homebrew/opt/sphinx-doc/bin:$PATH"' >> ~/.zshrc

# Apps
apps=(
    visual-studio-code
)

# Install apps to /Applications
# Default is: /Users/$user/Applications
echo "installing apps with Cask..."
brew install --cask --appdir="/Applications" "${apps[@]}"

# Install Python dependency manager Poetry
echo "Installing poetry..."
brew install poetry
echo 'export PATH="/opt/homebrew/opt/qt@5/bin:$PATH"' >> ~/.bash_profile
echo 'export LDFLAGS="-L/opt/homebrew/opt/qt@5/lib"' >> ~/.bash_profile
echo 'export CPPFLAGS="-I/opt/homebrew/opt/qt@5/include"' >> ~/.bash_profile
echo 'export PKG_CONFIG_PATH="/opt/homebrew/opt/qt@5/lib/pkgconfig"' >> ~/.bash_profile
# Install poetry plugins
poetry self update
poetry completions zsh > ~/.zfunc/_poetry
echo 'fpath+=~/.zfunc' >> ~/.zshrc
echo 'autoload -Uz compinit && compinit' >> ~/.zshrc
poetry self add poetry-plugin-export

# Install nbdime and enable git integration
poetry add nbdime -G dev
nbdime config-git --enable --global
nbdime extensions --enable

# Cleanup homebrew
brew cleanup

# Log in to GitHub
gh auth login