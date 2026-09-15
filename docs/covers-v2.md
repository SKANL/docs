# Declarative covers

V2 covers are authored in the document configuration under `format.cover`.
The same specification feeds the editable DOCX compositor and the semantic
HTML projection; PDF remains derived from the DOCX renderer.

```json
{
  "mode": "generated",
  "variant": "academic",
  "content": {
    "title": "{{document.title}}",
    "author": "{{author.name}}",
    "organization": "{{organization.name}}"
  },
  "visual": {
    "logo": "assets/logo.png",
    "hero": "assets/hero.png"
  },
  "layout": { "hero_width_in": 6.25, "logo_width_in": 1.35 }
}
```

Supported variants are `academic`, `institutional`, `technical`, `minimal`,
`visual`, and `custom`. The standard slot resolver accepts canonical paths
such as `document.title`, `author.name`, `organization.name`, `course.name`,
`advisor.name`, `document.version`, `document.status`, `date`, and
`custom.*`, while retaining legacy top-level and context aliases.

`content` has precedence over the legacy `slots` block. Missing slots are
reported during `compose-cover`; strict and release policies block them.
Configured `logo` and `hero` files are validated for existence and dimensions
before rendering. Relative assets resolve from `paths.assets_dir`, and valid
images are embedded in DOCX relationships and emitted as accessible HTML
`<img>` elements with alt text. `mode: none` disables inherited covers.
