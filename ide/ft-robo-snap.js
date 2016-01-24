/*
 * Initialize the connection to the RoboWeb websocket and start Snap! with the FTRoboTXT blocks preloaded.
 *
 * (c) 2016 Richard Kunze
 *
 * This file is part of FT-Robo-Snap (https://github.com/rkunze/ft-robo-snap)
 *
 * FT-Robo-Snap is free software licensed under the Affero Gnu Public License, either version 3
 * or (at your discretion) any later version.
 */
var world;
window.onload = function () {
    world = new WorldMorph(document.getElementById('world'));
    world.worldCanvas.focus();
    new IDE_Morph().openIn(world);
    loop();
};
function loop() {
    requestAnimationFrame(loop);
    world.doOneCycle();
}

