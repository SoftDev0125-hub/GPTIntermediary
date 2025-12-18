# 🔐 Authentication System Setup Guide

Complete guide for the login/registration and admin approval system.

## 📋 Overview

Your app now has a complete authentication system with:
- ✅ **Login Page** - Email/password authentication
- ✅ **User Registration** - Self-service account creation  
- ✅ **Admin Approval** - All new users must be approved by an administrator
- ✅ **JWT Tokens** - Secure session management
- ✅ **Password Hashing** - Using bcrypt for security
- ✅ **Admin Panel** - Approve/reject pending users

---

## 🚀 Quick Start

### Step 1: Set Up Supabase Database

Follow the `DATABASE_SETUP.md` guide to:
1. Create a Supabase account
2. Create a new project
3. Get your DATABASE_URL connection string
4. Add it to your `.env` file

### Step 2: Initialize Database with Admin User

```bash
python init_database.py
```

This creates:
- All database tables
- A default admin user with these credentials:
  - **Email:** `admin@example.com`
  - **Password:** `admin123`
  - **⚠️ IMPORTANT:** Change this password after first login!

### Step 3: Start the Application

```bash
python app.py
```

The app will open the **login page** automatically.

### Step 4: Login as Admin

1. Enter email: `admin@example.com`
2. Enter password: `admin123`
3. Click "Sign In"

You're now logged in! 🎉

---

## 📖 User Flow

### For New Users:

1. **Register Account**
   - Click "Register" tab on login page
   - Fill in: Full Name, Email, Password
   - Click "Create Account"
   - See message: "Registration successful! Pending admin approval"

2. **Wait for Approval**
   - Admin must approve your account
   - You'll see error if you try to login before approval: "Account pending admin approval"

3. **Login After Approval**
   - Once approved by admin, you can login
   - Your session lasts 7 days (token expiry)

### For Administrators:

1. **Login to Admin Account**
   - Use admin@example.com / admin123 (or your credentials)

2. **Access Admin Panel**
   - After login, go to: http://localhost:5000/admin_panel.html
   - Or add a link in your app interface

3. **Approve/Reject Users**
   - See list of pending users
   - Click "✓ Approve" to activate account
   - Click "✗ Reject" to delete request

---

## 🔧 Configuration

### Environment Variables

Add to your `.env` file:

```env
# Database (required)
DATABASE_URL=postgresql://your_supabase_connection_string

# JWT Secret Key (optional, but recommended for production)
SECRET_KEY=your-very-secure-random-secret-key-here

# OpenAI API (existing)
OPENAI_API_KEY=your_openai_key
```

### Generate Secure Secret Key

```python
import secrets
print(secrets.token_urlsafe(32))
```

Copy the output and use it as your `SECRET_KEY` in `.env`.

---

## 📁 Files Created

### Frontend:
- **`login.html`** - Login/registration page
- **`admin_panel.html`** - Admin user management interface

### Backend:
- **`auth_utils.py`** - Password hashing and JWT token utilities
- Authentication endpoints in **`main.py`**:
  - `POST /api/auth/register` - User registration
  - `POST /api/auth/login` - User login
  - `GET /api/auth/verify` - Token verification
  - `GET /api/auth/pending-users` - Get users awaiting approval (admin only)
  - `POST /api/auth/approve-user/{user_id}` - Approve user (admin only)
  - `POST /api/auth/reject-user/{user_id}` - Reject user (admin only)

### Database:
- **`db_models.py`** - User model already has all required fields:
  - `username`
  - `email`
  - `hashed_password`
  - `full_name`
  - `is_active` (used for admin approval)
  - `is_admin` (admin access flag)

---

## 🔒 Security Features

### Password Security:
✅ **Bcrypt hashing** - Industry-standard password hashing  
✅ **Salt included** - Automatic per-password salting  
✅ **No plaintext storage** - Passwords never stored in plain text  

### Token Security:
✅ **JWT tokens** - JSON Web Tokens for stateless sessions  
✅ **7-day expiry** - Tokens expire after 1 week  
✅ **Signature verification** - Tokens can't be forged  
✅ **Bearer authentication** - Standard HTTP Authorization header  

### Access Control:
✅ **Admin-only endpoints** - Protected endpoints check admin status  
✅ **Token validation** - All protected routes verify tokens  
✅ **Account approval** - New users can't login until approved  

---

## 🎯 API Endpoints

### Register New User

```http
POST /api/auth/register
Content-Type: application/json

{
  "name": "John Doe",
  "email": "john@example.com",
  "password": "secure_password_123"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Registration successful! Your account is pending admin approval.",
  "user_id": 2
}
```

---

### Login

```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "john@example.com",
  "password": "secure_password_123"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Login successful",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user_id": 2,
  "user_name": "John Doe",
  "is_admin": false
}
```

---

### Verify Token

```http
GET /api/auth/verify
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Response:**
```json
{
  "success": true,
  "user_id": 2,
  "email": "john@example.com",
  "name": "John Doe",
  "is_admin": false
}
```

---

### Get Pending Users (Admin Only)

```http
GET /api/auth/pending-users
Authorization: Bearer {admin_token}
```

**Response:**
```json
{
  "success": true,
  "users": [
    {
      "id": 3,
      "username": "jane",
      "email": "jane@example.com",
      "full_name": "Jane Smith",
      "created_at": "2024-12-17T10:30:00"
    }
  ]
}
```

---

### Approve User (Admin Only)

```http
POST /api/auth/approve-user/3
Authorization: Bearer {admin_token}
```

**Response:**
```json
{
  "success": true,
  "message": "User jane@example.com approved successfully"
}
```

---

### Reject User (Admin Only)

```http
POST /api/auth/reject-user/3
Authorization: Bearer {admin_token}
```

**Response:**
```json
{
  "success": true,
  "message": "User jane@example.com rejected and removed"
}
```

---

## 🧪 Testing the Authentication

### Test 1: Register New User

1. Open app → You see login page
2. Click "Register" tab
3. Fill in name, email, password
4. Click "Create Account"
5. Should see success message

### Test 2: Try Login Before Approval

1. Try to login with the email you just registered
2. Should see: "Account pending admin approval"

### Test 3: Admin Approves User

1. Login as admin (admin@example.com / admin123)
2. Go to http://localhost:5000/admin_panel.html
3. See pending user in table
4. Click "✓ Approve"
5. User should disappear from list

### Test 4: Login After Approval

1. Logout
2. Login with the approved user credentials
3. Should work and redirect to chat interface

---

## 🎨 Customization

### Change Token Expiry Time

In `auth_utils.py`:

```python
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days instead of 7
```

### Auto-Approve Users (No Admin Approval)

In `main.py`, change the registration endpoint:

```python
new_user = User(
    ...
    is_active=True,  # Change from False to True
    ...
)
```

### Add Email Notifications

Install: `pip install python-sendgrid` or use your email service

Add to registration endpoint:
```python
# After user creation
send_notification_email(admin_email, f"New user registered: {email}")
```

Add to approval endpoint:
```python
# After approval
send_approval_email(user.email, "Your account has been approved!")
```

---

## 🔐 Production Best Practices

### Before Deploying:

1. ✅ **Change Default Admin Password**
   - Login and update admin@example.com password
   - Or delete and create new admin user

2. ✅ **Use Secure SECRET_KEY**
   - Generate random key: `secrets.token_urlsafe(32)`
   - Never commit to Git
   - Store in environment variables

3. ✅ **Enable HTTPS**
   - Use SSL/TLS certificates
   - Redirect HTTP → HTTPS
   - Set secure cookie flags

4. ✅ **Rate Limiting**
   - Add rate limiting to login endpoint
   - Prevent brute force attacks
   - Use libraries like `slowapi`

5. ✅ **Email Verification**
   - Add email verification step
   - Send confirmation links
   - Verify before admin approval

6. ✅ **Password Requirements** (Already Implemented!)
   - Minimum 6 characters
   - At least one uppercase letter
   - At least one number
   - At least one special character
   - Validated on both frontend and backend

---

## 📝 Database Schema

The `users` table includes:

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Primary key |
| `username` | String(100) | Unique username |
| `email` | String(255) | Unique email address |
| `hashed_password` | String(255) | Bcrypt hashed password |
| `full_name` | String(255) | User's full name |
| `is_active` | Boolean | Account approved? (default: False) |
| `is_admin` | Boolean | Administrator? (default: False) |
| `created_at` | DateTime | Registration timestamp |
| `last_login` | DateTime | Last login time |

---

## ❓ Troubleshooting

### "Authentication not available" Error

**Cause:** Missing Python packages

**Solution:**
```bash
pip install passlib bcrypt python-jose[cryptography] python-multipart
```

---

### "Database not available" Error

**Cause:** Supabase not configured or wrong DATABASE_URL

**Solution:**
1. Check `.env` file has `DATABASE_URL`
2. Verify connection string is correct
3. Test connection: `python init_database.py`

---

### Can't Login as Admin

**Cause:** Database not initialized or wrong credentials

**Solution:**
1. Run: `python init_database.py`
2. Use: admin@example.com / admin123
3. Check database has users table

---

### Token Expired Error

**Cause:** Token is older than 7 days

**Solution:**
1. User must login again
2. Frontend automatically clears expired tokens
3. Increase expiry time in `auth_utils.py` if needed

---

### Admin Panel Shows 403 Error

**Cause:** User is not an admin

**Solution:**
1. Make sure you're logged in as admin
2. Check `is_admin` flag in database
3. Only admin@example.com has admin rights by default

---

## 🔄 Workflow Diagram

```
┌─────────────────┐
│   User Visits   │
│      App        │
└────────┬────────┘
         │
         v
┌─────────────────┐
│  Login Page     │  ← Shows first
│  (login.html)   │
└────┬───────┬────┘
     │       │
Login│       │Register
     │       │
     v       v
┌──────┐  ┌──────────────┐
│Valid?│  │ Registration │
│ Yes  │  │  Successful  │
└──┬───┘  └──────┬───────┘
   │             │
   │             v
   │      ┌──────────────┐
   │      │   is_active  │
   │      │    = False   │
   │      └──────┬───────┘
   │             │
   │             v
   │      ┌──────────────┐
   │      │Admin Approval│
   │      │   Required   │
   │      └──────┬───────┘
   │             │
   │      ┌──────v───────┐
   │      │ Admin Opens  │
   │      │ Admin Panel  │
   │      └──────┬───────┘
   │             │
   │      ┌──────v───────┐
   │      │Admin Approves│
   │      │  is_active   │
   │      │   = True     │
   │      └──────┬───────┘
   │             │
   └─────────────┤
                 v
         ┌───────────────┐
         │ Chat Interface│
         │ (main app)    │
         └───────────────┘
```

---

## 📚 Additional Resources

- **FastAPI Security:** https://fastapi.tiangolo.com/tutorial/security/
- **JWT Tokens:** https://jwt.io/
- **Bcrypt:** https://github.com/pyca/bcrypt/
- **OWASP Auth Guide:** https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html

---

## ✅ Checklist

- [ ] Set up Supabase database
- [ ] Add DATABASE_URL to `.env`
- [ ] Run `python init_database.py`
- [ ] Test login as admin (admin@example.com / admin123)
- [ ] Change default admin password
- [ ] Test user registration flow
- [ ] Test admin approval in admin panel
- [ ] Generate secure SECRET_KEY for production
- [ ] Add admin panel link to main app interface

---

**🎉 Your authentication system is ready to use!**

Users can now register, wait for admin approval, and access your app securely.

