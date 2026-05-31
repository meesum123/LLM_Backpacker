#!/bin/bash
# Packages lambda_function.py + dependencies into deployment.zip
# Usage: ./deploy.sh
# Then upload deployment.zip to your Lambda function in the AWS console.
#
# Lambda IAM role needs these permissions:
#   s3:GetObject      on arn:aws:s3:::YOUR_BUCKET/YOUR_PREFIX*
#   ses:SendEmail     on *  (or scope to verified identity ARN)
#
# GitHub Actions deploy needs a separate IAM user with:
#   lambda:UpdateFunctionCode  on the specific function ARN

set -e

PACKAGE_DIR="package"
ZIP_NAME="deployment.zip"

echo "Cleaning up..."
rm -rf "$PACKAGE_DIR" "$ZIP_NAME"

echo "Installing dependencies..."
# boto3 is pre-installed in the Lambda runtime, but including it here
# ensures the local package dir is self-contained.
pip install -r requirements.txt -t "$PACKAGE_DIR" --quiet

echo "Copying function code..."
cp lambda_function.py "$PACKAGE_DIR/"

echo "Zipping..."
cd "$PACKAGE_DIR"
zip -r "../$ZIP_NAME" . --quiet
cd ..

echo "Done: $ZIP_NAME ($(du -sh $ZIP_NAME | cut -f1))"
echo ""
echo "Next: upload $ZIP_NAME in the AWS Lambda console → your function → Upload from → .zip file"
