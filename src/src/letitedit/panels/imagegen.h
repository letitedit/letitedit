/*
 * Copyright (c) 2026 Meltytech, LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef IMAGEGEN_H
#define IMAGEGEN_H

class MainWindow;

// letitedit's Image generator: a prompt, reference images, "edit this image", how many, wide or tall, what was made for this
// video, and put one on the timeline. It sends its requests through the visible chat, like the app's other AI buttons, and the
// AI calls the same tool it uses by itself (bridge/image_gen.py, letitedit_image). The history is read from the video's side
// folder (<video>.letitedit/images). The one switch here is the person's: whether another AI on this PC may draw for the AI in
// use (panel.json image_other_ai; off until they turn it on, after a plain notice).
namespace ImageGenerator {

void show(MainWindow *window);

} // namespace ImageGenerator

#endif // IMAGEGEN_H
