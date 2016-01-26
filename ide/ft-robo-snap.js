/*
 * Initialize the connection to the RoboWeb websocket
 * and start Snap! with FT-Robo-Snap blocks preloaded.
 *
 * (c) 2016 Richard Kunze
 *
 * This file is part of FT-Robo-Snap (https://github.com/rkunze/ft-robo-snap)
 *
 * FT-Robo-Snap is free software licensed under the Affero Gnu Public License, either version 3
 * or (at your discretion) any later version.
 */

/*
   global
   SpriteMorph, StageMorph, SnapTranslator, WorldMorph, IDE_Morph,
   SyntaxElementMorph, TextMorph, requestAnimationFrame, localize,
   InputSlotMorph
*/


function FTRoboSnap() {
    this.dict = {}

    function blockFromInfo(info) {
        if (StageMorph.prototype.hiddenPrimitives[info.selector]) {
            return null;
        }
        var newBlock = SpriteMorph.prototype.blockFromInfo(info.selector, info, true);
        newBlock.isTemplate = true;
        return newBlock;
    }


    function monkeyPatchBlockTemplates(target) {
        var unpatched = target.prototype.blockTemplates;
        return function(category) {
            var blocks = unpatched.apply(this, arguments);
            var my_blocks = FTRoboSnap.blocks[category];
            if (my_blocks) {
                blocks.push("=");
                Array.prototype.push.apply(blocks, my_blocks.map(blockFromInfo));
            }
            return blocks;
        }
    }

    var original_initblocks = SpriteMorph.prototype.initBlocks;
    SpriteMorph.prototype.initBlocks = function() {
        // Call the original init to set up SpriteMorph.prototype.blocks
        original_initblocks.apply(this, arguments);

        // Patch our blocks into SpriteMorph.prototype.blocks
        Object.keys(FTRoboSnap.blocks).forEach(function(category){
            FTRoboSnap.blocks[category].forEach(function(spec){
                SpriteMorph.prototype.blocks[spec.selector] = spec;
            })
        });
    }

    SpriteMorph.prototype.blockTemplates = monkeyPatchBlockTemplates(SpriteMorph);
    StageMorph.prototype.blockTemplates = monkeyPatchBlockTemplates(StageMorph);

    var unpatchedLabelPart = SyntaxElementMorph.prototype.labelPart;
    SyntaxElementMorph.prototype.labelPart = function (spec) {
        var spec_or_constructor = FTRoboSnap.labelSpecs[spec];
        if (typeof(spec_or_constructor) === 'function') {
            return spec_or_constructor(spec);
        } else if (typeof(spec_or_constructor) === 'string') {
            spec = spec_or_constructor;
        }
        return unpatchedLabelPart.apply(this, arguments);
    }
}

FTRoboSnap.prototype.monkeyPatchTranslation = function(script) {
    var install_language_handler = script.onload
    var lang = /lang-(..)\.js/.exec(script.src)[1];
    var orig_translation = document.getElementById('language-base');
    var orig_src = '/snap/lang-' + lang + '.js';

    script.onload = undefined;
    if (orig_translation) {
        document.head.removeChild(orig_translation);
    }
    orig_translation = document.createElement('script');
    orig_translation.id = 'language-base';
    orig_translation.onload = function () {
        var target_dict = SnapTranslator.dict[lang];
        var src_dict = FTRoboSnap.dict[lang];
        Object.keys(src_dict).forEach(function(key){
            target_dict[key] = src_dict[key];
        });
        install_language_handler();
    };
    document.head.appendChild(orig_translation);
    orig_translation.src = orig_src;

}
// our specialized label part specs definitions. The entries
// may be either functions that create the appropriate morph, or
// strings to translate a custom label spec to a standard label spec
FTRoboSnap.prototype.labelSpecs = function() {
    function choice(editable, choices, initial) {
        return function() {
        var part = new InputSlotMorph(
            null,
            typeof(initial) == 'number',
            choices,
            !editable
        );
        if (initial) {
            part.setContents([choices[initial]]);
        }
        return part;
    }}
    function enumchoice(prefix, n) {
        var result = {}
        for (var i = 1; i <= n; i++) {
            var value = prefix + i;
            result[value] = value;
        }
        return result;
    }

    var labelSpecs = {

        "$ftrobo" : "$robot", // map our prefix to a robot image
        // TODO
        "%ftroboInput" :      choice(false, enumchoice("I", 8), "I1"),
        "%ftroboOutput" :     choice(false, enumchoice("O", 8), "O1"),
        "%ftroboCounter" :    choice(false, enumchoice("C", 4), "C1"),
        "%ftroboMotor" :      choice(false, enumchoice("M", 4), "M1"),
        "%ftroboMotorOrNone": choice(false, enumchoice("M", 4), null),
        "%ftroboOutputValue" :choice(true, {'0 (off)' : 0, '512 (max)': 512}, 0),
        "%ftroboMotorValue" : choice(true, {'+512 (forward)' : 512, '0 (stop)': '0', '-512 (back)' : -512}, 0),
    }
    return labelSpecs;
}();

// Block specs by category, in palette order.
// Our block specs have an additional property "selector"
// which defines the selector for the block, and they may
// omit the "category" (defaults to the category of the
// palette the block is placed in).
// Note: the selector is automatically prefixed with "ftrobo" in order
// to avoid naming collisons with standard blocks, and the spec is prefixed
// with "$ftrobo " in order to make our blocks easily identifiable
//
FTRoboSnap.prototype.blocks = function() {

    function blockspec(selector, type, spec, defaults, category) {
        return {
            selector: "ftrobo" + selector,
            type: type,
            spec: "$ftrobo " + spec,
            defaults: defaults,
            category: category
        };
    }
    function command(selector, spec, defaults, category) {
        return blockspec(selector, "command", spec, defaults, category);
    }
    function predicate(selector, spec, defaults, category) {
        return blockspec(selector, "predicate", spec, defaults, category);
    }
    function reporter(selector, spec, defaults, category) {
        return blockspec(selector, "reporter", spec, defaults, category);
    }

    var blockspecs = {
        motion: [
            command("SetOutput", "set %ftroboOutput to %ftroboOutputValue", ["O1", 0]),
            command("SetMotor", "run %ftroboMotor synchronized to %ftroboMotorOrNone %br at speed %ftroboMotorValue for %n steps",
                    ["M1", null, 0, '\u221e']),
            predicate("IsMotorOn", "motor %ftroboMotor is running?", ["M1"]),
        ],
        sensing: [
            predicate("IsSwitchClosed", "switch %ftroboInput is on?", ["I1"]),
            reporter("CounterValue", "current value of %ftroboCounter", ["C1"]),
            reporter("InputValue", "current value of %ftroboInput", ["I1"]),
        ]
    }

    Object.keys(blockspecs).forEach(function(category){
        blockspecs[category].forEach(function(spec){
            spec.category = spec.category ? spec.category : category;
            SpriteMorph.prototype.blocks[spec.selector] = spec;
        })
    });
    return blockspecs;
}();

// Patch our block specs into SpriteMorph.prototype.blocks

var FTRoboSnap = new FTRoboSnap()


// IDE startup. Copied here from snap.html because I like my JavaScript code
// to reside in .js files...
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

