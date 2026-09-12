import cProfile, pstats
cProfile.run('import Obylon', 'obylon.prof')
p = pstats.Stats('obylon.prof')
p.sort_stats('cumulative').print_stats(30)
