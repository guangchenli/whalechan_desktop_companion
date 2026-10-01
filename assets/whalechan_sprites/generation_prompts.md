# whalechan generation prompts

Mode: built-in image generation, transparent background requested.
Reference: original spritesheet.webp. Later action sheets also use redrawn idle sheet as the character/style reference.

## Shared specification

Use case: illustration-story. Asset: one transparent-background animation sprite sheet for the character named whalechan (name for asset metadata, NEVER write the name on the artwork).
Reference image is the original character and animation reference. Precisely preserve the identity of whalechan: tiny full-body super-deformed anime maid, large head about half the total height, long navy-blue wavy hair with cyan-blue ends, large blue eyes, white ruffled maid headband, navy dress with white collar and cuffs, white ruffled apron with a small navy whale emblem, small gold dress trim and bows, white socks, navy shoes, a curved navy whale tail at her side. Whale-themed character, no shark teeth, no redesign.
Redraw the art crisply with fine dark outlines and simple cel shading, faithful to the reference, no extra props unless required by this action.
Every frame must show the same character model, costume details, size and camera angle. Equal-size rectangular cells, exact grid, evenly spaced centered sprites, entire head/hair/tail/hands/feet inside their cell, generous transparent gutters, sharp silhouette and fully transparent background. Clean alpha edges, no green fringe, no floor, no cast shadow, no checkerboard, no black or white background. No text, numbers, grid lines, borders or watermark. Frames read left-to-right then top-to-bottom. Subtle pose-to-pose changes should form a usable animation rather than unrelated illustrations.

## idle

Layout: six frames in a 3-column by 2-row grid.

Redraw the TOP ROW of the original reference: front-facing idle breathing/blinking. Six sequential frames: relaxed smiling eyes open, eyes happily closed, eyes reopen, brief relaxed blink, small surprised open mouth, relaxed smile again. Arms at sides. Same planted feet and baseline, only tiny body bob and tail sway.

## walk_right

Layout: eight frames in a 4-column by 2-row grid.

Redraw ROW 2 of the original reference: side-view walking to the RIGHT, facing right in EVERY frame. Eight sequential distinct poses forming one full walk cycle: alternating foot contact, passing pose, opposite foot contact, passing pose. Arms counter-swing, hair and whale tail trail to the left, character does not translate across its cell.

## walk_left

Layout: eight frames in a 4-column by 2-row grid.

Redraw ROW 3 of the original reference: side-view walking to the LEFT, facing left in EVERY frame. Eight sequential distinct poses forming one full walk cycle: alternating foot contact, passing pose, opposite foot contact, passing pose. Arms counter-swing, hair and whale tail trail to the right, character does not translate across its cell.

## wave

Layout: four frames in a 2-column by 2-row grid.

Redraw ROW 4 of the original reference: front-facing cheerful greeting wave. Four sequential poses: arm lowered, right hand (viewer left) raised with open palm, open palm lifted slightly higher and tilted outward, palm returns inward. Friendly smile, left arm relaxed, feet remain planted.

## jump

Layout: five frames in a 3-column by 2-row grid; bottom-right sixth cell completely EMPTY and transparent.

Redraw ROW 5 of the original reference: joyful hop/jump. Exactly five sequential poses: anticipation crouch with fists beside cheeks, deeper crouch, takeoff raising both fists, airborne with both shoes clearly off baseline, landing back into relaxed standing. Keep the same cell-local coordinate system so the airborne sprite genuinely rises a little. No action rays or extra props.

## sad

Layout: eight frames in a 4-column by 2-row grid.

Redraw ROW 6 of the original reference: front-facing subdued sad/sulking animation. Both hands rest together on front of apron, shoulders lowered, worried/downturned mouth. Eight subtle sequential poses with slowly lowering head, sad blink, head rising slightly, gentle whale-tail droop and sway. No tears or extra symbols.

## happy

Layout: six frames in a 3-column by 2-row grid.

Redraw ROW 7 of the original reference: front-facing happy delighted animation. Both hands clasped just beneath chin, smiling with bright blue eyes. Six sequential poses: gentle bounce and slight head tilt right then center then left then center, hands remain clasped, subtle swaying hair and tail. No hearts, stars or extra props.

## sleepy

Layout: six frames in a 3-column by 2-row grid.

Redraw ROW 8 of the original reference: front-facing sleepy/resting animation. Hands together at chest; mouth small and calm, blue eyes gradually close and reopen as she nods gently. Six sequential poses: drowsy eyes open, eyes closed, eyes reopen, lowered head, eyes closed, return to initial drowsy pose. Keep standing feet planted. No bed or added sleeping symbols.

## think

Layout: six frames in a 3-column by 2-row grid.

Redraw ROW 9 of the original reference: thoughtful thinking animation. One hand at chin while opposite arm crosses torso. Six sequential poses: glance slightly sideways, finger touching chin, head tilted, eyes closed thinking, lean forward slightly with curious face, return to chin pose. Preserve full body and costume, no lightbulb in this action.

## notification

Layout: six frames in a 3-column by 2-row grid.

New-message notification action in six sequential frames: 1 relaxed attentive front-facing, 2 eyes widen slightly and right elbow bends, 3 right hand raised beside head with ONLY index finger pointing vertically upwards, 4 hold pointing pose, 5 a small saturated YELLOW LIGHTBULB pops into existence directly ABOVE fingertip, 6 bulb shines clearly with three short yellow rays as whalechan smiles. Bulb absent in first FOUR frames. Stable feet and scale; reserve overhead space in every cell for bulb. No exclamation marks, no yellow rays before bulb appears, no large diffuse glow.

## Final anatomical corrections

For happy, sad, sleepy and think, remove duplicated idle hands at skirt sides, preserve the requested two hands in the expressive pose, and reconstruct skirt/hair cleanly. For wave and notification, remove any extra idle hand below the raised waving/pointing arm, preserving the other relaxed hand. Preserve character identity, expression, frame layout and transparency.

