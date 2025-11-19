#!/bin/bash
# Test script to verify pre-commit setup

echo "🧪 Testing pre-commit setup..."

# Check if pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo "❌ pre-commit not found. Installing..."
    pip install pre-commit
fi

# Install hooks
echo "🔧 Installing pre-commit hooks..."
pre-commit install

# Test Django checks
echo "🔍 Testing Django system checks..."
python manage.py check

# Test migrations check
echo "🗄️ Testing migrations check..."
python manage.py makemigrations --check --dry-run

# Test our standings tests specifically
echo "🏒 Testing standings logic..."
python manage.py test core.tests.test_standings

# Run pre-commit on specific files to test
echo "🧹 Testing pre-commit hooks..."
pre-commit run --files core/tests/test_standings.py

echo "✅ Pre-commit setup verification complete!"
