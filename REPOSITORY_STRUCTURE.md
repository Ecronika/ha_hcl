# Repository Structure for GitHub Upload

## Files to Upload to GitHub

```
ha_hcl/
├── custom_components/
│   └── hcl_lighting/
│       ├── __init__.py
│       ├── config_flow.py
│       ├── const.py
│       ├── manifest.json
│       ├── strings.json
│       ├── switch.py
│       └── translations/
│           ├── de.json
│           └── en.json
├── .gitignore
├── CHANGELOG.md
├── hacs.json
├── LICENSE
└── README.md
```

## Files to Exclude (Already in .gitignore)

These files should NOT be uploaded to GitHub:

- `hcl_kurven_interpolation_analyse.md` - Technical analysis document (German)
- `Hcl Kurven Interpolation Analyse.pdf` - PDF version of analysis
- `forum_post.md` - Forum announcement draft
- `hcl_lighting.zip` - Old archive files
- `2026-01-18 hcl_lighting.zip` - Old archive files

## Next Steps

1. **Initialize Git repository** (if not already done):
   ```bash
   cd c:\Users\tpaul\.gemini\antigravity\scratch\ha_hcl
   git init
   git add .
   git commit -m "Initial commit: HCL Lighting v0.1.0"
   ```

2. **Add remote and push**:
   ```bash
   git remote add origin https://github.com/Ecronika/ha_hcl.git
   git branch -M main
   git push -u origin main
   ```

3. **Create release tag**:
   ```bash
   git tag -a v0.1.0 -m "Release v0.1.0"
   git push origin v0.1.0
   ```

4. **Create GitHub Release**:
   - Go to https://github.com/Ecronika/ha_hcl/releases
   - Click "Create a new release"
   - Select tag `v0.1.0`
   - Title: `v0.1.0 - Initial Release`
   - Description: Copy from CHANGELOG.md
   - Publish release

## HACS Submission (Optional)

To make the integration available via HACS:

1. Ensure repository is public
2. Create a release (as above)
3. Submit to HACS: https://github.com/hacs/default/issues/new?template=integration.yml
4. Fill in the form with repository details

## Repository Settings Recommendations

- **Description**: "Human Centric Lighting integration for Home Assistant"
- **Topics**: `home-assistant`, `hcl`, `circadian-lighting`, `custom-component`, `hacs`
- **License**: MIT (already added)
