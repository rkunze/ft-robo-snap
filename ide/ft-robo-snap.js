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
   SyntaxElementMorph, requestAnimationFrame, MultiArgMorph,
   InputSlotMorph, SymbolMorph, newCanvas, Costume, Point, StringMorph
*/


function FTRoboSnap() {
    this.dict = {};

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

    function monkeyPatchBlocks(target) {
        Object.keys(FTRoboSnap.blocks).forEach(function(category){
            FTRoboSnap.blocks[category].forEach(function(spec){
                target.prototype.blocks[spec.selector] = spec;
            })
        });
    }

    var original_initblocks = SpriteMorph.prototype.initBlocks;
    SpriteMorph.prototype.initBlocks = function() {
        original_initblocks.apply(this, arguments);
        monkeyPatchBlocks(SpriteMorph);
    };

    SpriteMorph.prototype.blockTemplates = monkeyPatchBlockTemplates(SpriteMorph);
    StageMorph.prototype.blockTemplates = monkeyPatchBlockTemplates(StageMorph);

    var unpatchedLabelPart = SyntaxElementMorph.prototype.labelPart;
    SyntaxElementMorph.prototype.labelPart = function (spec) {
        var spec_or_constructor = FTRoboSnap.labelspecs[spec];
        if (typeof(spec_or_constructor) === 'function') {
            return spec_or_constructor(spec);
        } else if (typeof(spec_or_constructor) === 'string') {
            spec = spec_or_constructor;
        }
        return unpatchedLabelPart.apply(this, arguments);
    };
};


// our specialized label part specs definitions. The entries
// may be either functions that create the appropriate morph, or
// strings to translate a custom label spec to a standard label spec
FTRoboSnap.prototype.labelspecs = function() {
    var labelspecs = {
        "$ftrobo"           : ftlogo,
        "%ftroboInput"      : choice(false, enumchoice("I", 8), "I1"),
        "%ftroboOutput"     : choice(false, enumchoice("O", 8), "O1"),
        "%ftroboCounter"    : choice(false, enumchoice("C", 4), "C1"),
        "%ftroboMotor"      : choice(false, enumchoice("M", 4), "M1"),
        "%ftroboMotorList"  : function(){ return new MultiArgMorph("%ftroboMotor", null, 1); },
        "%ftroboMotorOrNone": choice(false, enumchoice("M", 4), ""),
        "%ftroboOutputValue": choice(true, {'0 (off)' : 0, '512 (max)': 512}, 0),
        "%ftroboMotorValue" : choice(true, {'+512 (forward)' : 512, '0 (stop)': "-", '-512 (back)' : -512}, 0),
        "%ftroboSteps"      : function() { var r = new InputSlotMorph(null, true); r.setContents('\u221e'); return r; },
    };

    // "ft" logo image
    var ftlogo_costume = undefined;
    var img = new Image();
    img.onload = function () {
        var canvas = newCanvas(new Point(img.width, img.height));
        canvas.getContext('2d').drawImage(img, 0, 0);
        ftlogo_costume = new Costume(canvas, "ft");
    };
    img.src = "ft.png";
    function ftlogo() {
        return ftlogo_costume ? new SymbolMorph(ftlogo_costume, 12) : new StringMorph("ft");
    }

    // private helper functions
    function choice(editable, choices, initial, numeric) {
        return function() {
        var part = new InputSlotMorph(
            null,
            numeric || typeof(initial) == 'number',
            choices,
            !editable
        );
        if (initial) {
            part.setContents([choices[initial]]);
        }
        return part;
    }}
    function enumchoice(prefix, n) {
        var result = {};
        for (var i = 1; i <= n; i++) {
            var value = prefix + i;
            result[value] = value;
        }
        return result;
    }

    return labelspecs;
}();


// FTRoboSnap block definitions and implementations.
// A block definition is an object with the properties
// * id: the selector (=id) of this block. Will be prefixed with
//   "ftrobo" for patching the imp into SpriteMorph/StageMorph/Process
// * type: the type of the block: "command", "predicate", "reporter" ...
// * spec: the block spec. Will be prefixed with "$ftrobo " before being
//         patched into SpriteMorph.blocks
// * defaults: the parameter defaults for the block. Optional
// * impl: the block implementation funtion.
// * category: the category for the block. Optional, defaults to "other"
// * palette: the palette where the block will be placed. Optional, defaults
//            to the category of the block (or to the "variables" palette
//            if category is "other")
//
// block specs will appear in their respective palette in the same order as they
// appear in the FTRoboSnap.blockdefs list.
FTRoboSnap.prototype.blockdefs = [
{
    id: "SetOutput", category: "motion", type: "command",
    spec: "set %ftroboOutput to %ftroboOutputValue",
    defaults: ["O1", null],
    impl: function() {
        alert("Not yet implemented...");
    }
},
{
    id: "SetMotor", category: "motion", type: "command",
    spec: "run %ftroboMotorList at speed %ftroboMotorValue %br and stop after %ftroboSteps steps",
    // defaults don't work right with a MultiArgMorph as first input slot...
    impl: function() {
        this.bubble("Not yet implemented...", true);
    }
},
{
    id: "IsMotorOn", category: "motion", type: "predicate",
    spec: "motor %ftroboMotor is running?",
    defaults: ["M1"],
    impl: function() {
        this.bubble("Not yet implemented...", true);
    }
},
{
    id: "IsSwitchClosed", category: "sensing", type: "predicate",
    spec: "switch %ftroboInput is on?",
    defaults: ["I1"],
    impl: function() {
        this.bubble("Not yet implemented...", true);
    }
},
{
    id : "CounterValue", category: "sensing", type: "reporter",
    spec: "current value of %ftroboCounter",
    defaults: ["C1"],
    impl: function() {
        this.bubble("Not yet implemented...", true);
    }
},
{
    id: "InputValue", category: "sensing", type: "reporter",
    spec: "current value of %ftroboInput",
    defaults: ["I1"],
    impl: function() {
        this.bubble("Not yet implemented...", true);
    }
}
];

FTRoboSnap.prototype.blockdefs.map(function(spec) {
    var selector = "ftrobo" + spec.id;
    SpriteMorph.prototype[selector] = spec.impl;
    StageMorph.prototype[selector] = spec.impl;
})

FTRoboSnap.prototype.blocks = function() {
    var blocks = {};
    for (var idx in FTRoboSnap.prototype.blockdefs) {
        var def = FTRoboSnap.prototype.blockdefs[idx];
        var palette = def.palette || def.category;
        var specs = blocks[palette];
        if (!specs) {
            specs = [];
            blocks[palette] = specs;
        }
        var spec = {
            selector : "ftrobo" + def.id,
            spec : "$ftrobo " + def.spec,
            category: def.category,
            defaults: def.defaults,
            type: def.type

        };
        specs.push(spec);
        blocks[palette] = specs;
    }
    return blocks;
}();


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

};

FTRoboSnap = new FTRoboSnap();

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

