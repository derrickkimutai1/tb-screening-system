"""
Services for the screening workflow.

Each service is a plain Python class that takes paths and arrays and returns
small result objects. None of them import the database models, so every one can
be tested without a database or an HTTP request. The view is what persists.
"""
