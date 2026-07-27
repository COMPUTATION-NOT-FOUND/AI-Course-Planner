# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root user and group
RUN addgroup --system appgroup && adduser --system --group appuser

# Change ownership of the app directory
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Define environment variable
ENV FLASK_APP=app.py

# Run gunicorn when the container launches
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "120", "app:app"]
