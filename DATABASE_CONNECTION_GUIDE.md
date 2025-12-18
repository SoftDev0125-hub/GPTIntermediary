# PostgreSQL Database Connection Guide

This guide will help you connect your GPTIntermediary application to your existing PostgreSQL database (`gptintermediarydb`).

## Prerequisites

1. PostgreSQL server running and accessible
2. Database `gptintermediarydb` already created
3. PostgreSQL credentials (username and password)

## Step 1: Configure Database Connection

Run the connection configuration script:

```bash
python connect_database.py
```

This script will:
- Ask for your PostgreSQL connection details (host, port, username, password)
- Test the connection to your database
- List existing tables in your database
- Save the connection string to your `.env` file

**Example:**
```
Host [localhost]: localhost
Port [5432]: 5432
Username [postgres]: postgres
Password: your_password_here
```

## Step 2: Test the Connection

After configuration, test the connection:

```bash
python test_connection.py
```

This will:
- Verify the connection works
- Show PostgreSQL version
- Display database size
- List all existing tables and their row counts

## Step 3: Initialize Database Tables

Create any missing tables (this won't modify existing tables):

```bash
python init_tables.py
```

This script will:
- Check existing tables in your database
- Create only tables that don't exist yet
- Preserve your existing `users` table and data

## Step 4: Start Your Application

```bash
python main.py
```

The application will:
- Connect to your database on startup
- Initialize tables if needed
- Enable authentication endpoints (`/api/auth/register`, `/api/auth/login`)

## Manual Configuration (Alternative)

If you prefer to configure manually, add this line to your `.env` file:

```env
DATABASE_URL=postgresql://username:password@host:port/gptintermediarydb
```

**Important:** If your password contains special characters, they must be URL-encoded:
- `@` → `%40`
- `#` → `%23`
- `$` → `%24`
- `%` → `%25`
- etc.

**Example:**
```env
DATABASE_URL=postgresql://postgres:mypass%40word@localhost:5432/gptintermediarydb
```

## Existing Database Structure

The application is designed to work with your existing `users` table structure:

- `id` (Integer, Primary Key)
- `name` (String)
- `email` (String, Unique)
- `password` (String) - stores hashed passwords
- `create_at` (DateTime)

The application will:
- ✅ Use your existing `users` table
- ✅ Save new registrations with hashed passwords
- ✅ Authenticate users against existing passwords
- ✅ Not modify existing user data
- ✅ Add new tables only if they don't exist

## Troubleshooting

### Connection Error: "password authentication failed"
- Check your username and password
- Verify PostgreSQL server is running
- Check PostgreSQL authentication settings (pg_hba.conf)

### Connection Error: "could not translate host name"
- Verify the hostname is correct
- Check if PostgreSQL is accessible from your machine
- Try using `localhost` or `127.0.0.1` instead of hostname

### Connection Error: "database does not exist"
- Make sure the database `gptintermediarydb` exists
- Check spelling of database name
- You can create it manually: `CREATE DATABASE gptintermediarydb;`

### "psql: command not found"
- This is normal on Windows if PostgreSQL bin is not in PATH
- Use the Python scripts instead (they don't require psql)

### Special Characters in Password
- Make sure to URL-encode special characters in the connection string
- The `connect_database.py` script handles this automatically

## Verification

After setup, verify everything works:

1. **Test connection:**
   ```bash
   python test_connection.py
   ```

2. **Check application logs:**
   When you start `main.py`, you should see:
   ```
   Database connection initialized successfully
   ```

3. **Test registration:**
   - Open your login page
   - Try registering a new user
   - Check the database to verify the user was created

## Next Steps

Once connected, you can:
- Register new users (data saved to `users` table)
- Login with existing users
- Access other database features as they're implemented

## Support

If you encounter issues:
1. Check the application logs
2. Run `test_connection.py` to verify database connectivity
3. Verify your `.env` file has the correct `DATABASE_URL`
4. Check PostgreSQL server logs for connection errors

