multibranchPipelineJob('diaries-client-pipeline') {
    branchSources {
        git {
            id = 'diaries-client-pipeline'
            remote('https://github.com/rsmaxwell/diaries-client-pipeline.git')
        }
    }
}
