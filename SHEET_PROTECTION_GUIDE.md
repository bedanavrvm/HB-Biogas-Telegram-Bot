# Google Sheet Protection Instructions

## Problem
Editors can currently modify ALL data in the Google Sheet, including bot-generated fields like timestamps and customer names.

## Solution
Restrict permissions so:
- ✅ Only the bot account can edit columns A-K (all data the bot creates)
- ✅ Team members can only VIEW most data
- ✅ Team members CAN EDIT columns L-M (complaint_status, resolution_details) to track case progress

## Step-by-Step Guide

### Step 1: Access Your Google Sheet
- URL: https://docs.google.com/spreadsheets/d/1VFRZgbux8crsjAvH7Cn-F5NZdG-dz3E2aB2vhJV_0hg
- Sign in with your account that has ownership

### Step 2: Downgrade Team Members to Viewers
1. Click **Share** (top right, blue button)
2. Under "Viewers and Comments", you'll see your team members
3. For each person:
   - Click on their name/email
   - Click the pencil icon next to their role
   - Select **Viewer** instead of **Editor**
   - Click **Save**
4. Keep only these with Editor access:
   - Yourself (for admin/configuration)
   - The service account: `biogas-bot-sheets@biogas-telegram-bot.iam.gserviceaccount.com`

### Step 3: Protect Bot-Generated Columns (A-K)
1. Select the range **A:K** by clicking column A header, then Shift+Click column K header
2. Right-click and select **Protect ranges**
3. In the popup:
   - **Name/Description**: "Bot-Generated Data - Read Only"
   - **Who can edit**: Click "Change" and select "Only you" (or add only service account email)
4. Click **Done**

### Step 4: Allow Editing of Status Columns (L-M)
1. Select columns **L and M** (the ones your team needs to update)
   - Click column L header, Shift+Click column M header
2. Right-click and select **Protect ranges**
3. In the popup:
   - **Name/Description**: "Team Updates - Status and Resolution"
   - **Who can edit**: Click "Change" and select:
     - Option A: "Anyone with edit access"
     - Option B: "Specific people" (add your team member emails)
4. Click **Done**

### Step 5: Protect Other Columns (N-R)
1. Select columns **N through R** (date_resolved, days_open, risk_level, message_id_backend, parsed_timestamp)
2. Right-click → **Protect ranges**
3. Configuration:
   - **Description**: "Bot-Generated Data - Read Only"
   - **Who can edit**: "Only you"
4. Click **Done**

---

## After Protection

✅ **What team members CAN do:**
- View all data (read-only)
- Click on complaint_status (column L) and resolution_details (column M) to edit
- Track case status as they resolve complaints

❌ **What team members CANNOT do:**
- Modify customer names, phone numbers, IDs (columns C-E)
- Modify timestamps or complaint descriptions (columns B, I)
- Delete or alter any bot-generated data

---

## Troubleshooting

**"I can't edit column L!"**
- You may have View-only access. Ask the sheet owner to:
  1. Share sheet with you as "Editor"
  2. Keep your access to Editor
  3. Only downgrade other team members to Viewer

**"I accidentally made myself Viewer"**
- Go to Share → Change yourself back to "Editor"
- Or contact the sheet owner

**Service account email for sharing:**
```
biogas-bot-sheets@biogas-telegram-bot.iam.gserviceaccount.com
```
Keep this account as Editor so the bot can write data.

---

## Testing

After protection:
1. Forward a message to your Telegram bot
2. Check the Google Sheet
3. Try to edit a customer name (should be locked ❌)
4. Try to edit complaint_status (should work ✅)
