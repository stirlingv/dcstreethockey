#!/bin/bash
# Setup script for dcstreethockey development environment

echo "🏒 Setting up DC Street Hockey development environment..."

# Check if virtual environment is activated
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo "⚠️  Virtual environment not detected. Please activate your virtual environment first:"
    echo "   source venv/bin/activate"
    exit 1
fi

# Install/update dependencies
echo "📦 Installing dependencies..."
pip install -r requirements-dev.txt

# Install pre-commit hooks
echo "🔧 Installing pre-commit hooks..."
pre-commit install

# Run initial pre-commit on all files (optional)
echo "🧹 Running pre-commit on all files (this may take a moment)..."
pre-commit run --all-files || true

# Run Django checks
echo "🔍 Running Django system checks..."
python manage.py check

# Check for migrations
echo "🗄️  Checking for pending migrations..."
python manage.py makemigrations --check --dry-run

# Run tests
echo "🧪 Running tests to ensure everything works..."
python manage.py test core.tests.test_standings

echo "✅ Setup complete! Pre-commit hooks are now installed."
echo ""
echo "ℹ️  Pre-commit will now run automatically before each commit and will:"
echo "   • Run Django system checks"
echo "   • Run all tests"
echo "   • Check for pending migrations"
echo "   • Format code with Black"
echo "   • Run flake8 linting"
echo "   • Check for common issues (trailing whitespace, large files, etc.)"
echo ""
echo "🚀 You're ready to develop!"
