import os
import sys
import time

import django
from datetime import datetime

from api.Y.y_tiem import Timer

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from general.models import AmazonShop
list_a = [{'name': '承诺希航', 'divi_shop_id': 2234}, {'name': '海边-01刘嘉华', 'divi_shop_id': 2400}, {'name': '海边-03周礼应', 'divi_shop_id': 2401}, {'name': '海边-08黄延朝', 'divi_shop_id': 2402}, {'name': '海边-15文伟', 'divi_shop_id': 2404}, {'name': '海边-16黄剑军', 'divi_shop_id': 2406}, {'name': '海边-19叶进发', 'divi_shop_id': 2407}, {'name': '黄志雄-01王拯', 'divi_shop_id': 2410}, {'name': '海边-20欧维', 'divi_shop_id': 2411}, {'name': '黄志雄-02史学花', 'divi_shop_id': 2412}, {'name': '黄志雄-03马宏涛', 'divi_shop_id': 2413}, {'name': '海边-21凌家安', 'divi_shop_id': 2414}, {'name': '海边-22程笑', 'divi_shop_id': 2415}, {'name': '黄志雄-06曾小波', 'divi_shop_id': 2416}, {'name': '海边-23孙岐', 'divi_shop_id': 2417}, {'name': '海边-25罗仕琼', 'divi_shop_id': 2418}, {'name': '黄志雄-19杨炼', 'divi_shop_id': 2419}, {'name': '海边-27邱熙', 'divi_shop_id': 2420}, {'name': '海边-28方泽彬', 'divi_shop_id': 2421}, {'name': '海边-29范妮娜', 'divi_shop_id': 2422}, {'name': '黄志雄-22张珊珊', 'divi_shop_id': 2423}, {'name': '海边-31张翠芬', 'divi_shop_id': 2424}, {'name': '黄志雄-24孙景正', 'divi_shop_id': 2425}, {'name': '海边-32曾惠立', 'divi_shop_id': 2426}, {'name': '黄志雄-32黄志雄', 'divi_shop_id': 2427}, {'name': '海边-33张伍林', 'divi_shop_id': 2428}, {'name': '黄志雄-35叶雪茹', 'divi_shop_id': 2429}, {'name': '海边-34刘淑芳', 'divi_shop_id': 2430}, {'name': '黄志雄-38老挝09-LEELATDAVANH', 'divi_shop_id': 2431}, {'name': '海边-50谢小平', 'divi_shop_id': 2432}, {'name': '黄志雄-44刘晨宇', 'divi_shop_id': 2433}, {'name': '海边-58李臻', 'divi_shop_id': 2434}, {'name': '梁兵', 'divi_shop_id': 2435}, {'name': '黄志雄-45庞建龙', 'divi_shop_id': 2436}, {'name': '黄志雄-46贾庭安', 'divi_shop_id': 2437}, {'name': '黄志雄-47李四怀', 'divi_shop_id': 2438}, {'name': '黄志雄-48龙成艺', 'divi_shop_id': 2439}, {'name': '海边-60陈灿辉', 'divi_shop_id': 2440}, {'name': '黄志雄-49张军辉', 'divi_shop_id': 2441}, {'name': '黄志雄-50孙跃忠', 'divi_shop_id': 2442}, {'name': '海边-61黄家龙', 'divi_shop_id': 2443}, {'name': '惠城项目-12李尧尧', 'divi_shop_id': 2444}, {'name': '吴晓云-12田永添', 'divi_shop_id': 2445}, {'name': '吴晓云-15关志娟', 'divi_shop_id': 2446}, {'name': '惠城项目-11李嘉华', 'divi_shop_id': 2447}, {'name': '吴晓云-22吴晓军', 'divi_shop_id': 2448}, {'name': '吴晓云-23古足平', 'divi_shop_id': 2449}, {'name': '吴晓云-25梁郁海', 'divi_shop_id': 2450}, {'name': '吴晓云-26邵强', 'divi_shop_id': 2451}, {'name': '吴晓云-29曹家勇', 'divi_shop_id': 2452}, {'name': '海边-62陈胜虎', 'divi_shop_id': 2453}, {'name': '吴晓云-34黄云飞', 'divi_shop_id': 2454}, {'name': '吴晓云-35蔡彪', 'divi_shop_id': 2455}, {'name': '海边项目-63白杨', 'divi_shop_id': 2456}, {'name': '海边-64李亚', 'divi_shop_id': 2457}, {'name': '海边-65邱晓杰', 'divi_shop_id': 2459}, {'name': '吴晓云-38颜小群', 'divi_shop_id': 2460}, {'name': '海边-66邱文达', 'divi_shop_id': 2461}, {'name': '吴晓云-39黄云娟', 'divi_shop_id': 2462}, {'name': '海边-67古嘉维', 'divi_shop_id': 2463}, {'name': '吴晓云-40黄孝中', 'divi_shop_id': 2464}, {'name': '菅冀祁-01华阳医疗电子有限公司', 'divi_shop_id': 2465}, {'name': '海边-68张利红', 'divi_shop_id': 2466}, {'name': '海边-69温舒如', 'divi_shop_id': 2467}, {'name': '菅冀祁-02李祖廷', 'divi_shop_id': 2468}, {'name': '菅冀祁-04郭敏华-大陆', 'divi_shop_id': 2469}, {'name': '海边-70潘青蓝', 'divi_shop_id': 2470}, {'name': '菅冀祁-05周建明', 'divi_shop_id': 2471}, {'name': '海边-71张鹏', 'divi_shop_id': 2472}, {'name': '菅冀祁-08许秉达', 'divi_shop_id': 2473}, {'name': '海边-72郭震雨', 'divi_shop_id': 2474}, {'name': '海边-74武有忠', 'divi_shop_id': 2475}, {'name': '菅冀祁-09郭敏华-香港', 'divi_shop_id': 2476}, {'name': '海边-75杨小黑', 'divi_shop_id': 2477}, {'name': '菅冀祁-13杨红', 'divi_shop_id': 2478}, {'name': '海边-76武惠军', 'divi_shop_id': 2479}, {'name': '菅冀祁-14曹利敏', 'divi_shop_id': 2480}, {'name': '海边-77底占明', 'divi_shop_id': 2481}, {'name': '菅冀祁-17江鹏', 'divi_shop_id': 2482}, {'name': '海边-78武勇强', 'divi_shop_id': 2483}, {'name': '菅冀祁-21陈嘉敏', 'divi_shop_id': 2484}, {'name': '海边-79王志刚', 'divi_shop_id': 2485}, {'name': '海边-80武建国', 'divi_shop_id': 2486}, {'name': '胡赵玉-01黄婷婷', 'divi_shop_id': 2487}, {'name': '胡赵玉-04胡赵玉', 'divi_shop_id': 2488}, {'name': '胡赵玉-05吴惠华', 'divi_shop_id': 2489}, {'name': '海边-81史李辉', 'divi_shop_id': 2490}, {'name': '海边-82程永安', 'divi_shop_id': 2491}, {'name': '胡赵玉-10王志兵', 'divi_shop_id': 2492}, {'name': '海边-83王占云', 'divi_shop_id': 2493}, {'name': '胡赵玉-18王晓斌', 'divi_shop_id': 2494}, {'name': '海边-84张卫平', 'divi_shop_id': 2495}, {'name': '胡赵玉-19尹智', 'divi_shop_id': 2496}, {'name': '蔡宏-03袁理军', 'divi_shop_id': 2497}, {'name': '蔡宏-07刘婉盈', 'divi_shop_id': 2498}, {'name': '蔡宏-09王英丽', 'divi_shop_id': 2499}, {'name': '海边-141陈红基', 'divi_shop_id': 2500}, {'name': '蔡宏-11刘媛媛', 'divi_shop_id': 2501}, {'name': '林尾兰-05庄高玉', 'divi_shop_id': 2502}, {'name': '林尾兰-07叶嘉斌', 'divi_shop_id': 2503}, {'name': '林尾兰-11郑金山', 'divi_shop_id': 2504}, {'name': '林尾兰-13刘苗苗', 'divi_shop_id': 2505}, {'name': '廖瑜-05梁颖', 'divi_shop_id': 2506}, {'name': '廖瑜-06叶楚芬', 'divi_shop_id': 2507}, {'name': '廖瑜-07方华迪', 'divi_shop_id': 2508}, {'name': '廖瑜-09麦锦英', 'divi_shop_id': 2509}, {'name': '廖瑜-10麦锦辉', 'divi_shop_id': 2510}, {'name': '寻汇-07张文彬', 'divi_shop_id': 2511}, {'name': '寻汇-08杨思兰', 'divi_shop_id': 2512}, {'name': '寻汇-10李真', 'divi_shop_id': 2513}, {'name': '游锋-01游锋', 'divi_shop_id': 2514}, {'name': '菅冀祁-18邓惠珍', 'divi_shop_id': 2515}, {'name': '菅冀祁-19郑灿阳', 'divi_shop_id': 2516}, {'name': '菅冀祁-20张继祖', 'divi_shop_id': 2517}, {'name': '张艺-02肖文杰', 'divi_shop_id': 2518}, {'name': '张艺-03熊娇', 'divi_shop_id': 2519}, {'name': '张艺-09邬鑫', 'divi_shop_id': 2520}, {'name': '张艺-10赖丽芬', 'divi_shop_id': 2521}, {'name': '张艺-11江泽燕', 'divi_shop_id': 2522}, {'name': '海边-85卢勤龙', 'divi_shop_id': 2523}, {'name': '海边-86杨学昭', 'divi_shop_id': 2524}, {'name': '海边-87刘昊', 'divi_shop_id': 2525}, {'name': '海边-89杨勇', 'divi_shop_id': 2526}, {'name': '海边-90刘赞兴', 'divi_shop_id': 2527}, {'name': '海边-91肖勇', 'divi_shop_id': 2528}, {'name': '海边-92高明彬', 'divi_shop_id': 2529}, {'name': '海边-94王富春 ', 'divi_shop_id': 2530}, {'name': '海边-95郭亮', 'divi_shop_id': 2531}, {'name': '海边-96翟利平', 'divi_shop_id': 2532}, {'name': '海边-97呼利峰', 'divi_shop_id': 2533}, {'name': '海边-98刘富章', 'divi_shop_id': 2534}, {'name': '海边-99陈清芳', 'divi_shop_id': 2535}, {'name': '海边-101王桂平', 'divi_shop_id': 2536}, {'name': '海边-103白聪', 'divi_shop_id': 2537}, {'name': '海边-104刘福润', 'divi_shop_id': 2538}, {'name': '海边-105雷志刚', 'divi_shop_id': 2539}, {'name': '汤总-01房强', 'divi_shop_id': 2540}, {'name': '汤总-02吴乙锋', 'divi_shop_id': 2541}, {'name': '汤总-03莫永建', 'divi_shop_id': 2542}, {'name': '海边-102张建军', 'divi_shop_id': 2543}, {'name': '海边-106王卫鑫', 'divi_shop_id': 2549}, {'name': '海边-107肖惠鹏', 'divi_shop_id': 2658}, {'name': '海边-108赖惠平', 'divi_shop_id': 2659}, {'name': '汤总-04李志敏', 'divi_shop_id': 2677}, {'name': '汤总-05韩祥东', 'divi_shop_id': 2678}, {'name': '汤总-06张鹏飞', 'divi_shop_id': 2679}, {'name': '汤总-07马晶鑫', 'divi_shop_id': 2680}, {'name': '汤总-08李志明', 'divi_shop_id': 2681}, {'name': '汤总-09李勇恒', 'divi_shop_id': 2682}, {'name': '汤总-10杨志春', 'divi_shop_id': 2683}, {'name': '汤总-11高志东', 'divi_shop_id': 2684}, {'name': '海边-109何延泽', 'divi_shop_id': 2685}, {'name': '汤总-12张永强', 'divi_shop_id': 2686}, {'name': '汤总-13周志龙', 'divi_shop_id': 2687}, {'name': '海边-110刘伟权', 'divi_shop_id': 2691}, {'name': '海边-111刘明雷', 'divi_shop_id': 2692}, {'name': '海边-112李兴明', 'divi_shop_id': 2747}, {'name': '汤总-14银耀', 'divi_shop_id': 2748}, {'name': '承诺希航-01曾祥靖', 'divi_shop_id': 2749}, {'name': '承诺希航-02刘木勇', 'divi_shop_id': 2750}, {'name': '承诺希航-03叶植晓', 'divi_shop_id': 2751}, {'name': '承诺希航-04王芳', 'divi_shop_id': 2759}, {'name': '承诺希航-05李宁', 'divi_shop_id': 2760}, {'name': '承诺希航-06李兴龙', 'divi_shop_id': 2761}, {'name': '承诺希航-07李丽静', 'divi_shop_id': 2769}, {'name': '承诺希航-08李伟健', 'divi_shop_id': 2770}, {'name': '承诺希航-09马吉荣', 'divi_shop_id': 2771}, {'name': '海边-113邓月明', 'divi_shop_id': 2772}, {'name': '海边-114张利', 'divi_shop_id': 2773}, {'name': '海边-115冯淦龙', 'divi_shop_id': 2774}, {'name': '汤总-15李波', 'divi_shop_id': 2775}, {'name': '汤总-16黄祥龙', 'divi_shop_id': 2776}, {'name': '汤总-17薄雪强', 'divi_shop_id': 2791}, {'name': '汤总-18戴向召', 'divi_shop_id': 2792}, {'name': '汤总-19和小坡', 'divi_shop_id': 2793}, {'name': '汤总-20李帅帅', 'divi_shop_id': 2794}, {'name': '汤总-21李亚鹏', 'divi_shop_id': 2795}, {'name': '汤总-22韦祥', 'divi_shop_id': 2796}, {'name': '汤总-23杨仕洪', 'divi_shop_id': 2797}, {'name': '汤总-24郭正青', 'divi_shop_id': 2798}, {'name': '汤总-25李秋华', 'divi_shop_id': 2799}, {'name': '海边-116芦海平', 'divi_shop_id': 2800}, {'name': '海边-117顾明京', 'divi_shop_id': 2801}, {'name': '海边-118曲维东', 'divi_shop_id': 2802}, {'name': '海边-119何涛生', 'divi_shop_id': 2810}, {'name': '海边-120徐亚杰', 'divi_shop_id': 2811}, {'name': '海边-121刘红标', 'divi_shop_id': 2812}, {'name': '海边-122王妙芳', 'divi_shop_id': 2813}, {'name': '海边-123温亚萍', 'divi_shop_id': 2815}, {'name': '海边-124谢希长', 'divi_shop_id': 2816}, {'name': '海边-125凌少辉', 'divi_shop_id': 2817}, {'name': '海边-126文梦康', 'divi_shop_id': 2818}, {'name': '海边-127林善华', 'divi_shop_id': 2819}, {'name': '张野平-06杨长宝', 'divi_shop_id': 2820}, {'name': '海边-140黄楚帆', 'divi_shop_id': 2821}, {'name': '海边-128黄世銮', 'divi_shop_id': 2822}, {'name': '海边-129廖博', 'divi_shop_id': 2823}, {'name': '承诺希航-10陈光华', 'divi_shop_id': 2824}, {'name': '承诺希航-11石峰', 'divi_shop_id': 2825}, {'name': '承诺希航-12钟智扬', 'divi_shop_id': 2826}, {'name': '海边-130巫俊业', 'divi_shop_id': 2838}, {'name': '汤总-26陈记恩', 'divi_shop_id': 2839}, {'name': '汤总-27陈兴刚', 'divi_shop_id': 2840}, {'name': '汤总-28太春义', 'divi_shop_id': 2841}, {'name': '汤总-29周文汪', 'divi_shop_id': 2842}, {'name': '海边-133吴彩金', 'divi_shop_id': 2843}, {'name': '海边-134邬红波', 'divi_shop_id': 2844}, {'name': '汤总-32张杰', 'divi_shop_id': 2847}, {'name': '汤总-33任景运', 'divi_shop_id': 2848}, {'name': '海边-131杨宇振', 'divi_shop_id': 2849}, {'name': '海边-132高永昌', 'divi_shop_id': 2850}, {'name': '汤总-30郑观平', 'divi_shop_id': 2851}, {'name': '海边-135张法妹', 'divi_shop_id': 2852}, {'name': '海边-136张津源', 'divi_shop_id': 2859}, {'name': '汤总-31丘冠良', 'divi_shop_id': 2860}, {'name': '汤总-34张进军', 'divi_shop_id': 2861}, {'name': '汤总-35尤士杰', 'divi_shop_id': 2862}, {'name': '汤总-36程俊花', 'divi_shop_id': 2863}, {'name': '汤总-37郭俊文', 'divi_shop_id': 2864}, {'name': '汤总-38樊晓明', 'divi_shop_id': 2865}, {'name': '汤总-39田存徽', 'divi_shop_id': 2866}, {'name': '汤总-40赤业成', 'divi_shop_id': 2867}, {'name': '汤总-41林双凤', 'divi_shop_id': 2868}, {'name': '汤总-42孙少华', 'divi_shop_id': 2869}, {'name': '海边-137杨绍炬', 'divi_shop_id': 2870}, {'name': '汤总-43郭运浩', 'divi_shop_id': 2871}, {'name': '汤总-44王林军', 'divi_shop_id': 2872}, {'name': '汤总-45洪伟鹏', 'divi_shop_id': 2873}, {'name': '汤总-46纪超越', 'divi_shop_id': 2874}, {'name': '汤总-47叶瑛', 'divi_shop_id': 2875}, {'name': '惠城项目-05闫美琴', 'divi_shop_id': 2876}, {'name': '承诺希航-13王守亮', 'divi_shop_id': 2877}, {'name': '承诺希航-14高志勇', 'divi_shop_id': 2878}, {'name': '承诺希航-15孟永平', 'divi_shop_id': 2879}, {'name': '承诺希航-16蔡婉婷', 'divi_shop_id': 2880}, {'name': '承诺希航-17陈建煌', 'divi_shop_id': 2881}, {'name': '承诺希航-18李金鑫', 'divi_shop_id': 2882}, {'name': '承诺希航-19黄建成', 'divi_shop_id': 2883}, {'name': '承诺希航-20许永明', 'divi_shop_id': 2884}, {'name': '承诺希航-21智东亮', 'divi_shop_id': 2885}, {'name': '惠城项目-06胡仕轩', 'divi_shop_id': 2886}, {'name': '惠城项目-01陆永江', 'divi_shop_id': 2887}, {'name': '惠城项目-02贾磊', 'divi_shop_id': 2888}, {'name': '承诺希航-25周水其', 'divi_shop_id': 2889}, {'name': '承诺希航-26蔡美袖', 'divi_shop_id': 2890}, {'name': '承诺希航-27罗锦州', 'divi_shop_id': 2891}, {'name': '汤总-49潘泽荣', 'divi_shop_id': 2897}, {'name': '汤总-50刘浒', 'divi_shop_id': 2898}, {'name': '承诺希航-28潘吉棠', 'divi_shop_id': 2899}, {'name': '海边-138赖益铭', 'divi_shop_id': 2900}, {'name': '惠城项目-03林忠旋', 'divi_shop_id': 2901}, {'name': '承诺希航-31付玉乐', 'divi_shop_id': 2902}, {'name': '承诺希航-32翁伟隆', 'divi_shop_id': 2903}, {'name': '承诺希航-33薛新', 'divi_shop_id': 2904}, {'name': '承诺希航-34林培炎', 'divi_shop_id': 2905}, {'name': '承诺希航-35刘文学', 'divi_shop_id': 2906}, {'name': '承诺希航-36余旺华', 'divi_shop_id': 2909}, {'name': '惠城项目-07李玉文', 'divi_shop_id': 2910}, {'name': '承诺希航-38陈峰弟', 'divi_shop_id': 2911}, {'name': '承诺希航-39李九妹', 'divi_shop_id': 2912}, {'name': '承诺希航-40邬增红', 'divi_shop_id': 2913}, {'name': '承诺希航-41白欣', 'divi_shop_id': 2914}, {'name': '承诺希航-42秦浩翔', 'divi_shop_id': 2915}, {'name': '承诺希航-43张子新', 'divi_shop_id': 2916}, {'name': '承诺希航-44张秋妍', 'divi_shop_id': 2917}, {'name': '惠城项目-04张应花', 'divi_shop_id': 2926}, {'name': '承诺希航-46史深申', 'divi_shop_id': 2927}, {'name': '承诺希航-47李刚3', 'divi_shop_id': 2928}, {'name': '承诺希航-48段子耀', 'divi_shop_id': 2929}, {'name': '承诺希航-49张吉', 'divi_shop_id': 2930}, {'name': '承诺希航-50邢学军', 'divi_shop_id': 2931}, {'name': '承诺希航-51刘洪保', 'divi_shop_id': 2932}, {'name': '承诺希航-52谢杭州', 'divi_shop_id': 2933}, {'name': '惠城项目-08陈洪平', 'divi_shop_id': 2934}, {'name': '惠城项目-09许洪春', 'divi_shop_id': 2935}, {'name': '惠城项目-10周钟杰', 'divi_shop_id': 2936}, {'name': '承诺希航-56谢文帅', 'divi_shop_id': 2937}, {'name': '承诺希航-57童小伟', 'divi_shop_id': 2938}, {'name': '张野平-16方世虹', 'divi_shop_id': 2941}, {'name': '张野平-17李明翠', 'divi_shop_id': 2942}, {'name': '程莎-03肖继芳', 'divi_shop_id': 2943}, {'name': '程莎-01庞勇', 'divi_shop_id': 2953}, {'name': '程莎-02洪春祥', 'divi_shop_id': 2954}, {'name': '程莎-04刘根城', 'divi_shop_id': 2955}, {'name': '程莎-05李晟凯', 'divi_shop_id': 2956}, {'name': '承诺希航-63翟小丽 ', 'divi_shop_id': 2957}, {'name': '程莎-06詹坚文', 'divi_shop_id': 2958}, {'name': '程莎-07朱红兵', 'divi_shop_id': 2959}, {'name': '程莎-08郭虎', 'divi_shop_id': 2960}, {'name': '承诺希航-67杨磊', 'divi_shop_id': 2961}, {'name': '承诺希航-68叶根佐', 'divi_shop_id': 2962}, {'name': '承诺希航-73滕维', 'divi_shop_id': 2974}, {'name': '承诺希航-69王海军', 'divi_shop_id': 2975}, {'name': '承诺希航-70徐师军', 'divi_shop_id': 2976}, {'name': '程莎-09王英', 'divi_shop_id': 2977}, {'name': '承诺希航-72刘丹妮', 'divi_shop_id': 2978}, {'name': '承诺希航-74王嘉琪', 'divi_shop_id': 2982}, {'name': '汤总-51樊长焱', 'divi_shop_id': 2983}, {'name': '承诺希航-75沈伟煜', 'divi_shop_id': 2984}, {'name': '承诺希航-76任伟华', 'divi_shop_id': 2985}, {'name': '承诺希航-77刘奇', 'divi_shop_id': 2986}, {'name': '程莎-10杨金融', 'divi_shop_id': 3001}, {'name': '菅冀祁-22黄健萍', 'divi_shop_id': 3004}, {'name': '承诺希航-91邱春辉', 'divi_shop_id': 3026}, {'name': '承诺希航-93黄清荣（群主）', 'divi_shop_id': 3027}, {'name': '承诺希航-95刘康乐', 'divi_shop_id': 3028}, {'name': '承诺希航-97张焌烜', 'divi_shop_id': 3029}, {'name': '承诺希航-99任浩', 'divi_shop_id': 3030}, {'name': '承诺希航-101龚俊桦（群主）', 'divi_shop_id': 3031}, {'name': '承诺希航-103曾柔慧', 'divi_shop_id': 3032}, {'name': '承诺希航-105曾浩明', 'divi_shop_id': 3033}, {'name': '承诺希航-106黄忆源', 'divi_shop_id': 3034}, {'name': '承诺希航-104郑毅锐', 'divi_shop_id': 3035}, {'name': '承诺希航-107邓嘉丽', 'divi_shop_id': 3036}, {'name': '承诺希航-102魏占东', 'divi_shop_id': 3037}, {'name': '承诺希航-100谢斌（群主）', 'divi_shop_id': 3038}, {'name': '承诺希航-98陈笑盼（群主）', 'divi_shop_id': 3039}, {'name': '承诺希航-96谢清梅', 'divi_shop_id': 3040}, {'name': '承诺希航-94张杰人', 'divi_shop_id': 3041}, {'name': '承诺希航-92谢富鸣', 'divi_shop_id': 3042}, {'name': '承诺希航-90阮镜华', 'divi_shop_id': 3043}, {'name': '承诺希航-89谢海权', 'divi_shop_id': 3044}, {'name': '承诺希航-88罗浩东', 'divi_shop_id': 3045}, {'name': '承诺希航-87徐鑫明', 'divi_shop_id': 3046}, {'name': '承诺希航-86陈茂静', 'divi_shop_id': 3047}, {'name': '承诺希航-85徐建鑫', 'divi_shop_id': 3048}, {'name': '承诺希航-84陈艳娥', 'divi_shop_id': 3049}, {'name': '承诺希航-110徐世凯', 'divi_shop_id': 3050}, {'name': '承诺希航-83徐助权', 'divi_shop_id': 3051}, {'name': '承诺希航-82罗俊新', 'divi_shop_id': 3052}, {'name': '承诺希航-81欧小婷', 'divi_shop_id': 3053}, {'name': '承诺希航-108丁德华', 'divi_shop_id': 3054}, {'name': '承诺希航-109杜孝棣', 'divi_shop_id': 3055}, {'name': '承诺希航-80陈小海（群主）', 'divi_shop_id': 3056}, {'name': '承诺希航-79何舒红', 'divi_shop_id': 3057}]
print(len(list_a))

# ========== 查找并对比 AmazonShop 数据 ==========
print("=" * 80)
print("开始查找 list_a 中的 name 在 AmazonShop 中的匹配情况")
print("=" * 80)

# 存储结果分类
matched = []           # 名字和 divi_shop_id 都匹配
mismatched = []        # 名字存在但 divi_shop_id 不匹配
not_found = []         # 名字在数据库中不存在

for item in list_a:
    name = item['name']
    expected_divi_shop_id = item['divi_shop_id']
    
    # 查找数据库中是否有该 name 的记录
    shops = AmazonShop.objects.filter(shop_name=name)
    
    if shops.exists():
        for shop in shops:
            actual_divi_shop_id = shop.divi_shop_id
            
            if actual_divi_shop_id == expected_divi_shop_id:
                matched.append({
                    'name': name,
                    'expected_divi_shop_id': expected_divi_shop_id,
                    'actual_divi_shop_id': actual_divi_shop_id
                })
            else:
                mismatched.append({
                    'name': name,
                    'expected_divi_shop_id': expected_divi_shop_id,
                    'actual_divi_shop_id': actual_divi_shop_id
                })
                shop.divi_shop_id = expected_divi_shop_id  # 以 list_a 为准修正
                shop.save()  # 保存到数据库
    else:
        not_found.append({
            'name': name,
            'expected_divi_shop_id': expected_divi_shop_id
        })

# 打印匹配的结果
print("\n" + "=" * 80)
print(f"✅ 匹配成功（共 {len(matched)} 条）- 名字和 divi_shop_id 都匹配")
print("=" * 80)
for item in matched:
    print(f"  名字: {item['name']}")
    print(f"  divi_shop_id: {item['actual_divi_shop_id']}")
    print("-" * 40)

# 打印不匹配的结果
print("\n" + "=" * 80)
print(f"⚠️  匹配失败（共 {len(mismatched)} 条）- shop_name 存在但 divi_shop_id 不匹配")
print("=" * 80)
for item in mismatched:
    print(f"  名字: {item['name']}")
    print(f"  期望 divi_shop_id: {item['expected_divi_shop_id']}")
    print(f"  实际 divi_shop_id: {item['actual_divi_shop_id']}")
    print("-" * 40)

# 打印不存在的名字
print("\n" + "=" * 80)
print(f"❌ shop_name 不存在（共 {len(not_found)} 条）- 在 AmazonShop 中找不到")
print("=" * 80)
for item in not_found:
    print(f"  名字: {item['name']}")
    print(f"  期望 divi_shop_id: {item['expected_divi_shop_id']}")
    print("-" * 40)

# 汇总统计
print("\n" + "=" * 80)
print("汇总统计")
print("=" * 80)
print(f"总记录数: {len(list_a)}")
print(f"匹配成功: {len(matched)}")
print(f"匹配失败: {len(mismatched)}")
print(f"名字不存在: {len(not_found)}")
