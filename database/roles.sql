-- Create the analytics application role if it does not already exist

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'analytics_app'
    ) THEN
        CREATE ROLE analytics_app
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOREPLICATION;
    END IF;
END
$$;


-- Make sure the role remains restricted

ALTER ROLE analytics_app
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION;


-- Every new session for this role should be read-only

ALTER ROLE analytics_app
    SET default_transaction_read_only = on;


-- Allow the role to connect to the project database

GRANT CONNECT
ON DATABASE ai_analytics
TO analytics_app;


-- Allow access to the public schema

GRANT USAGE
ON SCHEMA public
TO analytics_app;


-- Allow reading all existing tables

GRANT SELECT
ON ALL TABLES
IN SCHEMA public
TO analytics_app;


-- Explicitly remove write permissions

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON ALL TABLES
IN SCHEMA public
FROM analytics_app;


-- Future tables created by the database owner
-- should also be readable by analytics_app

ALTER DEFAULT PRIVILEGES
IN SCHEMA public
GRANT SELECT
ON TABLES
TO analytics_app;


-- Do not give write permissions on future tables

ALTER DEFAULT PRIVILEGES
IN SCHEMA public
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON TABLES
FROM analytics_app;