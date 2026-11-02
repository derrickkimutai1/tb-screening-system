# Publishing the model card

The Build Phase notes ask for a model card on the Hugging Face Hub. A **model
repository** is free, unlike the Docker Spaces this project had planned to
deploy on, so this part of the Hugging Face route still works and is worth
doing: it is the artefact that lets somebody evaluate the model without being
handed the whole system.

`README.md` in this folder is the card. On the Hub, a model repository's
`README.md` *is* its card, and the YAML header at the top is what fills in the
sidebar.

## Steps

1. <https://huggingface.co>, sign in, then **New** and **Model**.
   - Owner: the Strathmore organisation if Mrs Kirui has agreed it, otherwise
     your own username. A model under the organisation stays reachable after
     your account stops being the point of contact, which is what the notes
     mean about continuity.
   - Name: `tb-mobilenetv2-screening`
   - License: **other**, which matches the header in the card.
   - Visibility: public.

2. Upload three files with **Files**, **Add file**, **Upload files**:

   | From | Why |
   |---|---|
   | `ml/model-card/README.md` | the card |
   | `ml/models/tb_mobilenetv2_v1.keras` | the weights, about 10 MB |
   | `ml/models/metadata.json` | thresholds, preprocessing and provenance |

   The weights matter. A card describing a model nobody can obtain is a
   document, not a release, and the metadata is what makes the figures in the
   card reproducible: it carries the decision threshold, the exact
   preprocessing and the commit the weights came from.

3. Check the card renders. The header should give the pipeline as image
   classification and the library as Keras, and the tables should appear as
   tables.

## What not to upload

Not the datasets. Shenzhen and Montgomery are distributed by the U.S. National
Library of Medicine under their own terms, and republishing them here would
redistribute them rather than cite them. The card cites them instead.

Not `.env`, and nothing from `media/`. A screened radiograph belongs to a
patient; the model does not carry one and the repository must not either.

## Keeping it honest

If the model is retrained, the card stops being true the moment it is. Every
number in it comes from a file in `ml/artifacts/`, so regenerate those with
the scripts in `ml/scripts/` and update the card from the new files rather
than editing figures by hand. The project has already been bitten once by a
figure typed into a page that outlived the run that produced it.
