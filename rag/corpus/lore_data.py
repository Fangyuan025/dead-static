# -*- coding: utf-8 -*-
"""Hand-authored location flavor + atmospheric fragments.

Schema for every entry:
    id        str   unique short id, stable across runs (used for dedup)
    location  str   matches a key in game.LOCATIONS, or "*" for atmosphere
    weather   list  Weather.value strings; [] or None = applies to any weather
    time      list  TimeOfDay.value strings; [] or None = applies to any time
    tags      list  free-form keywords for BM25 boosting (optional)
    text_zh   str   Chinese flavor text, 1-3 sentences
    text_en   str   English flavor text, 1-3 sentences

Weather values:  "Clear skies", "Overcast", "Heavy rain", "Dense fog", "Thunderstorm"
Time values:     "Dawn", "Daytime", "Dusk", "Night"

Keep entries short and concrete. The LLM is told to borrow imagery —
not to quote verbatim — so specific sensory details travel best:
a smell, a sound, a stain, a small object.
"""

LORE_ENTRIES = [
    # ─────────────────────────── Abandoned Apartment ───────────────────────────
    {
        "id": "apt-01",
        "location": "Abandoned Apartment",
        "weather": None,
        "time": None,
        "tags": ["home", "family", "silence"],
        "text_zh": "冰箱门半开着，里面的牛奶早已分层。厨房地板上有三道深深的拖拽痕迹，一直延伸到卧室门口。墙上的全家福被人面朝下扣着。",
        "text_en": "The fridge door hangs ajar; the milk inside has long since separated. Three deep drag marks cross the kitchen floor to the bedroom door. A family photo on the wall has been turned face down.",
    },
    {
        "id": "apt-02",
        "location": "Abandoned Apartment",
        "weather": ["Heavy rain", "Thunderstorm"],
        "time": ["Night"],
        "tags": ["rain", "leak", "storm"],
        "text_zh": "雨水顺着阳台的裂缝滴进客厅，在地毯上积成一摊暗色的圆。每当闪电划过，窗帘背后就会短暂显出对街公寓里一动不动的人影。",
        "text_en": "Rain leaks in through a split along the balcony, pooling dark on the carpet. Each flash of lightning throws the silhouette of something standing very still in the apartment across the street.",
    },

    # ─────────────────────────── Main Street ───────────────────────────
    {
        "id": "street-01",
        "location": "Main Street",
        "weather": None,
        "time": ["Daytime", "Dawn"],
        "tags": ["cars", "blood", "abandoned"],
        "text_zh": "三辆车首尾相撞堵在十字路口，驾驶座上都空着，安全带还整齐地系在座位上。柏油路面上干涸的血渍拼出朝向医院方向的箭头。",
        "text_en": "Three cars piled nose-to-tail at the intersection; every driver's seat is empty, seatbelts still neatly buckled across nothing. Dried blood on the asphalt forms a ragged arrow pointing toward the hospital.",
    },
    {
        "id": "street-02",
        "location": "Main Street",
        "weather": ["Dense fog"],
        "time": None,
        "tags": ["fog", "visibility", "echo"],
        "text_zh": "雾浓得看不到两辆车之外。某个方向传来脚步声，节奏不对——太慢，太整齐，像是在绕圈。",
        "text_en": "The fog swallows everything past the second car. Footsteps rise from somewhere — the cadence wrong, too slow and too even, as if walking in a circle.",
    },

    # ─────────────────────────── Back Alley ───────────────────────────
    {
        "id": "alley-01",
        "location": "Back Alley",
        "weather": None,
        "time": None,
        "tags": ["dumpster", "rot", "graffiti"],
        "text_zh": "垃圾箱旁边堆着一排啃得干干净净的骨头，规整得像是谁特意摆好的。砖墙上有人用红漆写着：'不要回头看。'",
        "text_en": "A tidy row of picked-clean bones lies beside the dumpster, arranged as if by hand. On the brick wall, someone has spray-painted in red: 'Don't look back.'",
    },
    {
        "id": "alley-02",
        "location": "Back Alley",
        "weather": ["Heavy rain"],
        "time": None,
        "tags": ["rain", "runoff", "gutter"],
        "text_zh": "排水沟里漂着粉色的水——太粉了，不是铁锈。一只狗项圈卡在格栅上，挂牌上的名字被指甲刮掉了。",
        "text_en": "The gutter runs pink — too pink to be rust. A dog's collar is snagged on the grate, the name tag scratched clean with a fingernail.",
    },

    # ─────────────────────────── Rooftop ───────────────────────────
    {
        "id": "roof-01",
        "location": "Rooftop",
        "weather": ["Clear skies", "Overcast"],
        "time": ["Daytime", "Dusk"],
        "tags": ["view", "skyline", "smoke"],
        "text_zh": "从这里能看到整座城市。东边的三栋高楼还在冒烟，烟柱笔直，像是已经烧了好几天。远处传来偶尔的枪声，越来越稀。",
        "text_en": "The city unfolds from up here. Three towers to the east still trail smoke in straight, patient columns — burning for days now. Gunfire cracks in the distance, thinning out.",
    },
    {
        "id": "roof-02",
        "location": "Rooftop",
        "weather": None,
        "time": ["Night"],
        "tags": ["stars", "wind", "lights"],
        "text_zh": "整片城市没有一盏灯。没有光污染之后，银河像一条白色的河贴着地平线。风把远处某扇门反复拍打的声音送上来。",
        "text_en": "Not a single light burns in the city below. Without the haze, the Milky Way runs along the horizon like a pale river. The wind carries up the rhythmic slam of a door somewhere far away.",
    },

    # ─────────────────────────── Grocery Store ───────────────────────────
    {
        "id": "grocery-01",
        "location": "Grocery Store",
        "weather": None,
        "time": None,
        "tags": ["shelves", "looted", "cold aisle"],
        "text_zh": "货架东倒西歪，地上全是踩扁的麦片和玻璃碴。冷藏柜的门还半开着，一股变质的肉味和冰凉的风一起扑出来。",
        "text_en": "Shelves lean into each other; cereal and broken glass crunch underfoot. The cold-aisle doors hang half open, breathing out a wave of chilled air and spoiled meat.",
    },
    {
        "id": "grocery-02",
        "location": "Grocery Store",
        "weather": None,
        "time": ["Night"],
        "tags": ["emergency light", "humming", "register"],
        "text_zh": "只有收银台上方的应急灯还亮着，把一切染成病态的绿色。POS机在电池剩余的最后一口气里，一遍又一遍打印着一张空白小票。",
        "text_en": "Only the emergency light above the register still works, washing everything in a sick green. On its last gasp of battery, the POS printer keeps spitting out blank receipts, over and over.",
    },

    # ─────────────────────────── Police Station ───────────────────────────
    {
        "id": "police-01",
        "location": "Police Station",
        "weather": None,
        "time": None,
        "tags": ["barricade", "cells", "siege"],
        "text_zh": "大厅的桌椅堆成了一道矮墙，朝门的一面插满了弹壳。墙上用粉笔记着数字：38、42、53——像是在数什么。最后一个数被涂掉了。",
        "text_en": "Desks and chairs have been dragged into a low barricade facing the doors, its front edge studded with shell casings. Numbers are chalked on the wall — 38, 42, 53 — like a tally. The last one has been scrubbed out.",
    },
    {
        "id": "police-02",
        "location": "Police Station",
        "weather": None,
        "time": ["Night", "Dusk"],
        "tags": ["cell", "radio static", "flashlight"],
        "text_zh": "拘留室深处传来有节奏的敲击声。警用电台还在沙沙作响，每隔几分钟插进一句被切断的呼救，然后归于静电。",
        "text_en": "A rhythmic tap echoes from deep in the holding cells. The dispatch radio still hisses, broken every few minutes by a cut-off cry for help, then static again.",
    },

    # ─────────────────────────── Hospital ───────────────────────────
    {
        "id": "hosp-01",
        "location": "Hospital",
        "weather": None,
        "time": None,
        "tags": ["corridor", "antiseptic", "patient"],
        "text_zh": "走廊两侧的病床都空着，床单被褥扯到地上，像是有人同时惊醒逃跑。消毒水的味道被更重的东西盖住——甜腻、发酵、靠近喉咙。",
        "text_en": "The corridor beds are empty, sheets and blankets dragged onto the floor as if everyone bolted in the same instant. The smell of antiseptic has been swallowed by something heavier — sweet, fermented, catching in the throat.",
    },
    {
        "id": "hosp-02",
        "location": "Hospital",
        "weather": None,
        "time": ["Night"],
        "tags": ["monitor", "wheelchair", "dark"],
        "text_zh": "某间病房的心电监护仪还在响，滴、滴、滴——病床上没有人。走廊尽头一辆轮椅自己慢慢地朝你这边转过来，又停下。",
        "text_en": "In one room, a cardiac monitor still beeps — beep, beep, beep — over an empty bed. At the far end of the hall, a wheelchair turns slowly toward you of its own accord, then stops.",
    },

    # ─────────────────────────── Hospital Basement ───────────────────────────
    {
        "id": "hbase-01",
        "location": "Hospital Basement",
        "weather": None,
        "time": None,
        "tags": ["morgue", "formaldehyde", "generator"],
        "text_zh": "太平间的柜门全都是开的。发电机在墙后沉重地哼，偶尔咳嗽一下。某个柜子深处还在往外渗暗色的液体，沿着瓷砖缝慢慢爬。",
        "text_en": "Every morgue drawer is open. The generator hums heavily behind the wall, coughing now and then. From somewhere deep in one drawer, a dark fluid still seeps, tracing the grout line tile by tile.",
    },
    {
        "id": "hbase-02",
        "location": "Hospital Basement",
        "weather": None,
        "time": None,
        "tags": ["trial", "experimental", "quarantine"],
        "text_zh": "一间上锁的研究室门上贴着红色的隔离令，日期只比感染爆发早一周。玻璃观察窗后面，几排IV架整齐地立着，每一袋都接着同一种淡蓝色液体。",
        "text_en": "One locked research room carries a red quarantine order — dated just a week before the outbreak. Behind the observation window, rows of IV stands are lined up neatly, every bag feeding the same pale blue fluid.",
    },

    # ─────────────────────────── Pawn Shop ───────────────────────────
    {
        "id": "pawn-01",
        "location": "Pawn Shop",
        "weather": None,
        "time": None,
        "tags": ["display case", "gold", "registry"],
        "text_zh": "展柜的玻璃基本都完好——说明洗劫者进来以后改了主意。柜台后面的典当本摊开着，最后一条写的是一把结婚戒指，备注栏里只有两个字：'对不起。'",
        "text_en": "Most of the display cases are unbroken — whoever came to loot changed their mind. The pawn ledger lies open on the counter; the last entry, a wedding ring, has only two words in the notes: 'I'm sorry.'",
    },
    {
        "id": "pawn-02",
        "location": "Pawn Shop",
        "weather": None,
        "time": None,
        "tags": ["iron bars", "owner", "photo"],
        "text_zh": "铁栏后的店主倒在他自己的霰弹枪旁边。墙上贴着他和孙女的合照，孙女穿着学位服。地板上有一圈用盐画的粗糙圆形，已经被风吹散了一半。",
        "text_en": "Behind the iron bars, the owner lies beside his own shotgun. A photo on the wall shows him with his granddaughter in a graduation gown. A rough circle of salt, half-scattered, is drawn on the floor.",
    },

    # ─────────────────────────── Sewer Entrance ───────────────────────────
    {
        "id": "sewerent-01",
        "location": "Sewer Entrance",
        "weather": None,
        "time": None,
        "tags": ["grate", "damp", "descent"],
        "text_zh": "锈蚀的铁栅已经被人撬开过。踏上第一级台阶，下面涌上来的是一阵比空气温暖得多的气流，带着金属和腐烂的混合味道。",
        "text_en": "The rusted grate has been pried open once already. Step onto the first rung and the air rising from below is warmer than the street — metallic, with rot folded into it.",
    },
    {
        "id": "sewerent-02",
        "location": "Sewer Entrance",
        "weather": ["Heavy rain", "Thunderstorm"],
        "time": None,
        "tags": ["flood", "roar", "runoff"],
        "text_zh": "雨水正顺着街沟汹涌地往下灌，入口里传来放大的轰鸣。铁栅上缠着一条已经被泡白的围巾。",
        "text_en": "Rain pours down the street gutter; the entrance amplifies the roar into something cathedral-sized. A scarf — bleached pale by the water — is tangled around the grate.",
    },

    # ─────────────────────────── Sewer Tunnels ───────────────────────────
    {
        "id": "sewert-01",
        "location": "Sewer Tunnels",
        "weather": None,
        "time": None,
        "tags": ["dark", "water", "echo"],
        "text_zh": "脏水齐着小腿，每一步都荡起一圈浑浊的涟漪。远处岔道里传来低沉的水声，间隔太规律——像呼吸，不像水流。",
        "text_en": "Foul water rises to mid-calf, every step spreading a muddy ring. From a distant branch tunnel comes a low rush of water on a regular cycle — too regular. It sounds like breathing, not flow.",
    },
    {
        "id": "sewert-02",
        "location": "Sewer Tunnels",
        "weather": None,
        "time": None,
        "tags": ["camp", "survivors", "marking"],
        "text_zh": "隧道壁的粉笔箭头一路朝上游指。岔口处有人用铅笔写过字又擦掉，只剩下一个歪斜的'别'。天花板上挂着几根用完的荧光棒，绿光早已熄灭。",
        "text_en": "Chalk arrows along the tunnel wall all point upstream. At a junction someone wrote in pencil and then erased it, leaving only a crooked 'don't'. Spent glow sticks dangle from the ceiling, long since dark.",
    },

    # ─────────────────────────── River Bridge ───────────────────────────
    {
        "id": "bridge-01",
        "location": "River Bridge",
        "weather": None,
        "time": None,
        "tags": ["cars", "collapse", "crossing"],
        "text_zh": "桥中段塌了半边，只剩一条钢筋裸露的窄道。栏杆上绑着无数条褪色的红布，风一吹就整排颤抖，像是在替谁祈祷。",
        "text_en": "Half the bridge's midspan has gone; only a narrow ribbon of exposed rebar remains. Dozens of faded red cloths knot the railing, trembling together in the wind like a long unfinished prayer.",
    },
    {
        "id": "bridge-02",
        "location": "River Bridge",
        "weather": ["Dense fog", "Overcast"],
        "time": ["Dawn", "Dusk"],
        "tags": ["river", "fog", "silhouette"],
        "text_zh": "下方的河面被雾盖住，看不见水，只听见水声。偶尔雾被风吹开一道缝，能瞥见河里漂着的不是木头的形状。",
        "text_en": "Fog hides the river; you can hear the water but not see it. Now and then a gust tears the fog open for an instant, revealing things drifting on the current that aren't driftwood.",
    },

    # ─────────────────────────── Military Checkpoint ───────────────────────────
    {
        "id": "mil-01",
        "location": "Military Checkpoint",
        "weather": None,
        "time": None,
        "tags": ["sandbag", "sign", "equipment"],
        "text_zh": "沙袋墙上密密麻麻的弹孔朝着城市的方向——不是朝着外面。入口标牌被人用刺刀刻了新字：'这里没有救援。'",
        "text_en": "The sandbag wall is pocked with bullet holes — all facing back toward the city, not outward. A new line has been gouged into the entry sign with a bayonet: 'No rescue here.'",
    },
    {
        "id": "mil-02",
        "location": "Military Checkpoint",
        "weather": None,
        "time": None,
        "tags": ["radio", "orders", "retreat"],
        "text_zh": "指挥帐篷里的电台还开着，循环播放一条48小时前的撤离指令。作战地图上用红笔涂掉了这座城市，旁边写着'放弃'。",
        "text_en": "A field radio still runs in the command tent, looping an evacuation order from forty-eight hours ago. On the operations map the city has been crossed out in red, with one word beside it: 'abandon'.",
    },

    # ─────────────────────────── Evacuation Zone ───────────────────────────
    {
        "id": "evac-01",
        "location": "Evacuation Zone",
        "weather": None,
        "time": None,
        "tags": ["pad", "fence", "waiting"],
        "text_zh": "铁丝网围起来的停机坪上停着一架烧毁的旧直升机，骨架已经被掏空。风里飘着烧焦的塑料味，混着一点点希望——有人在登记簿上写下了自己的名字，但没划掉。",
        "text_en": "Inside the fenced pad sits a burnt-out old helicopter, its frame picked clean. The wind carries charred plastic and something almost like hope — someone wrote their name in the logbook but never crossed it off.",
    },
    {
        "id": "evac-02",
        "location": "Evacuation Zone",
        "weather": None,
        "time": ["Dawn"],
        "tags": ["dawn", "helicopter", "horizon"],
        "text_zh": "东方的天空开始泛白。停机坪的跑道灯一盏接一盏地闪烁起来，像是有人从很远的地方记起了这个地方。远处，低空有什么在震动。",
        "text_en": "The eastern sky pales to bone. One by one the pad's runway lights stutter awake, as if someone very far away has just remembered this place exists. Low on the horizon, something begins to vibrate the air.",
    },
]


ATMOSPHERE_FRAGMENTS = [
    # ─── Weather atmosphere ───
    {
        "id": "atm-rain-01",
        "location": "*",
        "weather": ["Heavy rain", "Thunderstorm"],
        "time": None,
        "tags": ["rain", "sound"],
        "text_zh": "雨把所有声音都盖住了——包括本该听见的脚步声。",
        "text_en": "The rain drowns every sound — including the footsteps you should be hearing.",
    },
    {
        "id": "atm-storm-01",
        "location": "*",
        "weather": ["Thunderstorm"],
        "time": None,
        "tags": ["lightning", "storm"],
        "text_zh": "每一次闪电都像快门按下，把眼前的景象钉在视网膜上一秒钟。",
        "text_en": "Every lightning flash fires like a shutter, pinning what's in front of you to the back of your eyes for one full second.",
    },
    {
        "id": "atm-fog-01",
        "location": "*",
        "weather": ["Dense fog"],
        "time": None,
        "tags": ["fog", "visibility"],
        "text_zh": "雾让十米之外的一切都变成模糊的轮廓。任何东西在你看清之前就已经够近了。",
        "text_en": "Beyond ten meters, fog smears everything into silhouette. Anything out there is already too close by the time you can tell what it is.",
    },
    {
        "id": "atm-overcast-01",
        "location": "*",
        "weather": ["Overcast"],
        "time": None,
        "tags": ["sky", "color"],
        "text_zh": "天空是均匀的铅灰色，没有影子，也没有方向感——像世界丢失了上下。",
        "text_en": "The sky is a flat lead grey — no shadows, no direction, as if the world has misplaced up and down.",
    },
    {
        "id": "atm-clear-01",
        "location": "*",
        "weather": ["Clear skies"],
        "time": ["Daytime"],
        "tags": ["sun", "clean"],
        "text_zh": "阳光干净得过分，把每一处血迹和裂缝都暴露得清清楚楚。美好的天气只让一切更像梦。",
        "text_en": "The sunlight is obscenely clean, showing every bloodstain and every crack in bald detail. Good weather only makes the whole thing feel more like a dream.",
    },

    # ─── Time-of-day atmosphere ───
    {
        "id": "atm-dawn-01",
        "location": "*",
        "weather": None,
        "time": ["Dawn"],
        "tags": ["dawn", "cold"],
        "text_zh": "天光像一层薄灰一样铺开。是一天里它们最慢的时候——但也是你最累的时候。",
        "text_en": "First light spreads like thin ash. It's the slowest hour for them — and the most exhausted hour for you.",
    },
    {
        "id": "atm-dusk-01",
        "location": "*",
        "weather": None,
        "time": ["Dusk"],
        "tags": ["dusk", "transition"],
        "text_zh": "最后一道光在天际线上拖着不肯走。再过二十分钟，每一个阴影都会站起来。",
        "text_en": "The last band of light drags along the skyline, unwilling to go. In twenty minutes every shadow will be standing up on its own.",
    },
    {
        "id": "atm-night-01",
        "location": "*",
        "weather": None,
        "time": ["Night"],
        "tags": ["night", "hearing"],
        "text_zh": "夜里你靠的是耳朵。每一声布料摩擦、每一次吞咽，它们都听得见。",
        "text_en": "At night you navigate by ear. Every scrape of fabric, every swallow — they hear it too.",
    },
    {
        "id": "atm-night-02",
        "location": "*",
        "weather": None,
        "time": ["Night"],
        "tags": ["night", "predator"],
        "text_zh": "夜里它们的动作会变快。没有人知道为什么。",
        "text_en": "They move faster at night. Nobody knows why.",
    },
    {
        "id": "atm-day-01",
        "location": "*",
        "weather": None,
        "time": ["Daytime"],
        "tags": ["day", "heat"],
        "text_zh": "白天它们更懒，但从不完全睡着。哪怕最热的时候，总有一只站着不动，眼睛没对准任何东西。",
        "text_en": "By day they're slower, but never fully asleep. Even in the worst heat, one of them is always upright, eyes aimed at nothing.",
    },

    # ─── General mood ───
    {
        "id": "atm-general-01",
        "location": "*",
        "weather": None,
        "time": None,
        "tags": ["silence", "city"],
        "text_zh": "这座城市最可怕的不是它的声音，而是没有了该有的那些——没有空调外机，没有远处的车流，没有狗叫。",
        "text_en": "What's worst about the city isn't the noises it makes — it's the ones missing. No air conditioners. No distant traffic. No dogs.",
    },
    {
        "id": "atm-general-02",
        "location": "*",
        "weather": None,
        "time": None,
        "tags": ["smell", "pervasive"],
        "text_zh": "那种味道你已经记不清什么时候开始闻不到的了——但当风换一个方向时，它还是会突然回来。",
        "text_en": "You can't remember when you stopped smelling it — but when the wind shifts, it comes back at you all at once.",
    },
]
