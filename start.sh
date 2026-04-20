#!/bin/bash
# Start script for Render deployment
# Starts the Django application with Gunicorn

echo "Starting Django application..."
exec gunicorn config.wsgi:application --log-file -