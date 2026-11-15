ROWS = {'hanzi': ['天地日月田由甲申中，', '距离说达到高处，出击说明。', '这场战斗是黑历史的重演吗？'], 'mixed': ["THE CRUSHER说：Let's go！", 'Side 3距离1.5km，确认目标。', 'RX-78-2与MS-013准备出击。'], 'hanzi-mixed': ['距离Side 3还有1.5km。', '机体RX-78-2与MS-013出击。', '确认AaBbXYZxyz与Hgypqj。']}
SAMPLES = {}
SAMPLES['story'] = {'y':61,'indent':True,'items':{k:'“'+('\n　'.join(v))+'”' for k,v in ROWS.items()}}
SAMPLES['flow'] = {'y':-48,'indent':False,'items':{k:'\n'.join(v) for k,v in ROWS.items()}}
SAMPLES['scroll'] = {'y':'first','indent':False,'settle':120,'items':{k:('\n'.join(v)+'\n　\n')*4 for k,v in ROWS.items()}}
