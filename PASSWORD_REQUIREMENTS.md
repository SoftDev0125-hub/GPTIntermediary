# 🔒 Password Requirements

## Password Policy

All user passwords must meet the following requirements:

### ✅ Required Rules:

1. **Minimum Length: 6 characters**
   - Example: `Pass1!` ✅
   - Example: `Pass1` ❌ (too short)

2. **At least 1 Uppercase Letter (A-Z)**
   - Example: `Password1!` ✅
   - Example: `password1!` ❌ (no uppercase)

3. **At least 1 Number (0-9)**
   - Example: `Pass1!` ✅
   - Example: `Pass!` ❌ (no number)

4. **At least 1 Special Character**
   - Allowed: `!@#$%^&*()_+-=[]{}|;:,.<>?/~\``
   - Example: `Pass1!` ✅
   - Example: `Pass1` ❌ (no special char)

---

## ✅ Valid Password Examples:

- `Admin1!` ✅
- `MyPass123!` ✅
- `Secure@2024` ✅
- `Welcome#123` ✅
- `Test$Pass1` ✅

## ❌ Invalid Password Examples:

- `admin123` ❌ - Missing uppercase and special character
- `ADMIN123` ❌ - Missing lowercase and special character  
- `Admin!` ❌ - Too short (needs 6+ characters)
- `Admin123` ❌ - Missing special character
- `Admin@` ❌ - Missing number
- `admin@1` ❌ - Missing uppercase letter

---

## 🎯 Password Strength Indicator

When registering, you'll see a color-coded strength indicator:

- 🔴 **Red (Weak)** - Does not meet all requirements
- 🟡 **Yellow (Medium)** - Meets most requirements
- 🟢 **Green (Strong)** - Meets all requirements

---

## 🛡️ Validation

Password requirements are validated in **two places**:

### 1. Frontend (login.html)
- Real-time validation as you type
- Visual feedback with strength indicator
- Clear error messages before submission

### 2. Backend (main.py)
- Server-side validation for security
- Prevents bypassing frontend checks
- Returns specific error messages

Both validations must pass for successful registration.

---

## 📝 Error Messages

You'll see these specific messages if requirements aren't met:

| Error | Requirement Not Met |
|-------|-------------------|
| "Password must be at least 6 characters long" | Length < 6 |
| "Password must include at least one uppercase letter" | No A-Z |
| "Password must include at least one number" | No 0-9 |
| "Password must include at least one special character" | No !@#$... |

---

## 💡 Tips for Strong Passwords

1. **Use a passphrase** - `MyDog#2024` is easier to remember than random characters
2. **Mix character types** - Combine letters, numbers, and symbols
3. **Avoid common words** - Don't use "password", "admin", etc.
4. **Make it unique** - Don't reuse passwords from other sites
5. **Use a password manager** - To generate and store complex passwords

---

## 🔄 Changing Password

The default admin password is:
- Email: `admin@example.com`
- Password: `admin123`

**⚠️ This does NOT meet the new requirements!**

To change it:
1. Login as admin
2. Go to profile/settings (future feature)
3. Or manually update in database

---

## 🧪 Testing Password Validation

### Test Case 1: Too Short
```
Input: "Pass1!"
Result: ❌ Error - "Password must be at least 6 characters long"
```

### Test Case 2: Missing Uppercase
```
Input: "password1!"
Result: ❌ Error - "Password must include at least one uppercase letter"
```

### Test Case 3: Missing Number
```
Input: "Password!"
Result: ❌ Error - "Password must include at least one number"
```

### Test Case 4: Missing Special Character
```
Input: "Password1"
Result: ❌ Error - "Password must include at least one special character"
```

### Test Case 5: All Requirements Met
```
Input: "Password1!"
Result: ✅ Success - Registration proceeds
```

---

## 🔧 Configuration

To change password requirements, edit these files:

### Frontend (`login.html`):
```javascript
function validatePassword(password) {
    // Minimum length (change 6 to your requirement)
    if (password.length < 6) {
        return { valid: false, message: '...' };
    }
    // ... other checks
}
```

### Backend (`main.py`):
```python
# Minimum length (change 6 to your requirement)
if len(password) < 6:
    return {
        "success": False,
        "message": "Password must be at least 6 characters long"
    }
```

**⚠️ Make sure to update BOTH frontend and backend!**

---

## 📊 Current Policy Summary

| Requirement | Minimum | Enforced |
|------------|---------|----------|
| Length | 6 characters | ✅ Yes |
| Uppercase | 1 letter | ✅ Yes |
| Lowercase | 0 (recommended) | ❌ No |
| Numbers | 1 digit | ✅ Yes |
| Special Chars | 1 symbol | ✅ Yes |

---

## 🚀 Implementation

Password validation was implemented in:
- **`login.html`** - Client-side validation with real-time feedback
- **`main.py`** - Server-side validation in `/api/auth/register` endpoint
- **`AUTH_SETUP.md`** - Documentation updated
- **`AUTHENTICATION_IMPLEMENTATION_SUMMARY.md`** - Summary updated

---

**Need help?** Check `AUTH_SETUP.md` for complete authentication documentation.

