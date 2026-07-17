# Deployment Guide — GitHub Pages

This guide gets your portfolio live on the web. No coding required. Estimated time: 10–15 minutes.

---

## What you'll have when you're done

A live URL like `https://yourusername.github.io/portfolio` that anyone can visit.

---

## Step 1 — Create a GitHub account

1. Go to [https://github.com](https://github.com)
2. Click **Sign up**
3. Choose a username (this will appear in your URL, so pick something clean — your name or initials work well)
4. Complete the setup

If you already have a GitHub account, skip to Step 2.

---

## Step 2 — Create a new repository

A "repository" (or "repo") is just a folder that GitHub stores and can serve as a website.

1. Once logged in, click the **+** icon in the top-right corner → **New repository**
2. Fill in the form:
   - **Repository name:** `portfolio` (lowercase, no spaces)
   - **Description:** optional — something like "Personal portfolio"
   - **Public** — make sure this is selected (GitHub Pages requires public repos on the free plan)
   - Leave everything else unchecked
3. Click **Create repository**

---

## Step 3 — Upload your files

You'll see an empty repository page. GitHub gives you an upload option.

1. Click **uploading an existing file** (the link in the middle of the page)
2. Drag and drop both files from your `portfolio/` folder:
   - `index.html`
   - `spec.json`
3. If you have images, drag those in too (keep them in a folder called `images/` — more on this below)
4. Scroll down, leave the commit message as-is, click **Commit changes**

---

## Step 4 — Enable GitHub Pages

This is the one toggle that turns your repo into a live website.

1. In your repository, click **Settings** (tab at the top)
2. In the left sidebar, click **Pages**
3. Under **Source**, select **Deploy from a branch**
4. Under **Branch**, select `main` and leave the folder as `/ (root)`
5. Click **Save**

---

## Step 5 — Get your live URL

1. Wait about 60–90 seconds
2. Refresh the Settings → Pages page
3. You'll see a green banner: **"Your site is live at https://yourusername.github.io/portfolio"**
4. Click it — your portfolio is live

---

## Adding images to a project

When you're ready to add images to a project:

1. In your GitHub repo, click **Add file** → **Upload files**
2. Create an `images/` folder by typing `images/` before your filename in the upload dialog — for example, `images/ai-enablement-screenshot.png`
3. Upload your image files
4. In `spec.json`, reference them like this:

```json
"images": ["images/ai-enablement-screenshot.png", "images/ai-enablement-flow.png"]
```

---

## Updating your portfolio later

The workflow is simple:

### To edit a project's content:
1. Open `spec.json` in a text editor (TextEdit on Mac works, but VS Code is better — it's free)
2. Find the project by its `"id"` field
3. Edit the `"body"` text, `"tags"`, `"title"`, or `"subtitle"`
4. Save the file
5. In GitHub, click on `spec.json` → the pencil icon to edit, or drag-drop a new version
6. Commit the change — site updates in ~30 seconds

### To add a new project (with my help):
1. Tell me the project name, description, and which folder it belongs in
2. I'll give you the new JSON block to paste into `spec.json`
3. Upload the updated file to GitHub

### To add a new Skill:
Same process — I'll write the new skill entry and you paste it into the `"skills"` folder array in `spec.json`.

---

## If something looks broken

- **Blank page:** Make sure both `index.html` AND `spec.json` are in the repository root (not inside a subfolder)
- **"Cannot find spec.json":** Same issue — both files need to be at the top level
- **Site not updating:** GitHub Pages can take up to 2 minutes to reflect changes. Hard-refresh the page (Cmd+Shift+R on Mac)

---

## Quick reference

| File | What it is | When you edit it |
|------|-----------|-----------------|
| `spec.json` | Your content — all project text, tags, folder structure | Every time you add/change a project |
| `index.html` | The site itself — layout, design, behavior | Only if you want a design change (I handle this) |
| `images/` | Your project screenshots/visuals | When you add images to a project |
