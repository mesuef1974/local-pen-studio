import subprocess,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import process_guard as guard

class ProcessGuardTests(unittest.TestCase):
    def test_windows_timeout_targets_only_the_owned_worker_tree(self):
        process=SimpleNamespace(pid=4321,poll=lambda:None,kill=Mock())
        with patch.object(guard.os,'name','nt'),patch.object(guard.subprocess,'run') as run:
            guard.terminate_tree(process)
        self.assertEqual(run.call_args.args[0],['taskkill','/PID','4321','/T','/F'])
        self.assertEqual(run.call_args.kwargs['timeout'],10)
    def test_timed_out_communication_terminates_and_drains_worker(self):
        process=SimpleNamespace(communicate=Mock(side_effect=[subprocess.TimeoutExpired('worker',1),('','')]))
        with patch.object(guard.subprocess,'Popen',return_value=process),patch.object(guard,'terminate_tree') as stop:
            with self.assertRaises(subprocess.TimeoutExpired):guard.run_bounded(['worker'],input='{}',timeout=1)
        stop.assert_called_once_with(process)
        self.assertEqual(process.communicate.call_args.kwargs,{'timeout':5})

if __name__=='__main__':unittest.main()
